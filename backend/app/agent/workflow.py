"""Leased parent orchestration with SQL receipts and independently checkpointed agents."""

from datetime import datetime, timedelta
import time
from typing import TypedDict
from uuid import NAMESPACE_URL, uuid4, uuid5

from langgraph.graph import END, START, StateGraph
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.agent.coordinator import plan_workflow
from app.agent.policy import BudgetExceeded, WorkflowBudget
from app.agent.specialists import invoke_specialist, SPECIALISTS
from app.common.exceptions import BusinessException
from app.models.users import User
from app.models.workflow import WorkflowRun, WorkflowStep
from app.services.space_discovery import SpaceConditions
from app.schemas.workflow import WorkflowPlan


MAX_MODELS, MAX_TOOLS, MAX_SECONDS = 13, 24, 180
DONE = {"completed", "skipped", "cancelled"}
RECEIPTS = {"pending", "return_pending", "returned", "reservation_pending", "reservation_approved", "reservation_rejected", "reservation_cancelled"}
SELECTIONS = {"select_book", "select_loan", "select_space"}
CONFIRMATIONS = {"confirm_borrow", "confirm_return", "confirm_reservation"}


def owned(db, user_id, workflow_id):
    run = db.query(WorkflowRun).filter_by(workflow_id=workflow_id, user_id=user_id).populate_existing().first()
    if run is None:
        raise BusinessException("组合任务不存在", 404)
    user = db.get(User, user_id)
    if user is None or user.status != 1:
        raise BusinessException("账号不可用", 403)
    if run.expires_at <= datetime.now():
        raise BusinessException("组合任务已过期，请创建新任务", 409)
    return run


def steps_for(db, workflow_id):
    return db.query(WorkflowStep).filter_by(workflow_id=workflow_id).populate_existing().order_by(WorkflowStep.position).all()


def create_workflow(db, user_id, request_id, query, conditions=None, *, plan=None, context=None):
    normalized = SpaceConditions.model_validate(conditions).model_dump(mode="json") if conditions else None
    request = {"query": query, "conditions": normalized}
    if plan is not None:
        request["plan"] = WorkflowPlan.model_validate(plan).model_dump()
        request["context"] = context or []
    existing = db.query(WorkflowRun).filter_by(workflow_id=request_id).first()
    if existing is not None:
        run = owned(db, user_id, request_id)
        if run.request != request:
            raise BusinessException("任务编号已绑定其他需求", 409)
        return operate(db, user_id, request_id)
    db.add(WorkflowRun(workflow_id=request_id, user_id=user_id, query=query, request=request,
        conditions=normalized, expires_at=datetime.now() + timedelta(hours=24)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        run = owned(db, user_id, request_id)
        if run.request != request:
            raise BusinessException("任务编号已绑定其他需求", 409)
        return operate(db, user_id, request_id)
    return operate(db, user_id, request_id, "retry")


def record_result(step, result):
    step.result = result
    status = result["status"]
    if status in RECEIPTS | {"answered"} or (step.spec["read_only"] and status in SELECTIONS | {"no_results"}):
        step.status = "completed"
    elif status == "cancelled":
        step.status = "cancelled"
    elif status in {"tool_unavailable", "no_results"}:
        step.status = "failed"
    else:
        step.status = "waiting"


def parent_status(run, steps):
    if run.status == "cancelled":
        return
    if not steps:
        return
    if all(step.status in DONE for step in steps):
        run.status = "completed"
        run.message = "所有步骤已结束，请查看每项结果；申请仍以管理员审核为准。"
    elif any(step.status == "failed" for step in steps):
        run.status = "partial_failure" if any(step.status == "completed" for step in steps) else "retryable"
    elif run.status not in {"needs_conditions", "budget_exceeded"}:
        run.status = "waiting" if any(step.status == "waiting" for step in steps) else "ready"


def view(db, run):
    steps = steps_for(db, run.workflow_id)
    return {"workflow_id": run.workflow_id, "query": run.query, "status": run.status,
        "message": run.message, "conditions": run.conditions, "expires_at": run.expires_at.isoformat(),
        "budget": {"model_calls": run.model_calls, "tool_calls": run.tool_calls,
            "active_seconds": round(run.active_seconds, 3), "max_models": MAX_MODELS, "max_tools": MAX_TOOLS},
        "steps": [{"id": step.id, "position": step.position, "child_run_id": step.child_run_id,
            "specialist": SPECIALISTS[step.spec["task_type"]], "spec": step.spec,
            "status": step.status, "result": step.result} for step in steps]}


def operate(db, user_id, workflow_id, operation="view", payload=None):
    run = owned(db, user_id, workflow_id)
    token = str(uuid4()); now = datetime.now(); started = time.monotonic()
    acquired = db.execute(update(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id,
        or_(WorkflowRun.lease_until.is_(None), WorkflowRun.lease_until < now)).values(
            lease_token=token, lease_until=now + timedelta(minutes=3))).rowcount
    db.commit()
    if not acquired:
        raise BusinessException("组合任务正在执行，请稍后刷新", 409)

    def reserve(kind):
        column, maximum = (WorkflowRun.model_calls, MAX_MODELS) if kind == "model" else (WorkflowRun.tool_calls, MAX_TOOLS)
        updated = db.execute(update(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.lease_token == token, column < maximum,
            WorkflowRun.active_seconds < MAX_SECONDS).values({column: column + 1})).rowcount
        db.commit()
        if not updated:
            raise BudgetExceeded()

    budget = WorkflowBudget(reserve=reserve, seconds=max(0.001, min(60, MAX_SECONDS - run.active_seconds)))
    try:
        steps = steps_for(db, workflow_id)
        if operation == "view":
            # No model/tool calls: reconcile durable child receipts and current business status.
            for step in steps:
                if step.result is not None or step.status in {"running", "failed"}:
                    result = invoke_specialist(db, user_id, step,
                        SpaceConditions.model_validate(run.conditions) if run.conditions else None, budget, "view")
                    if result is not None:
                        if step.status in {"skipped", "cancelled"}:
                            step.result = result
                        else:
                            record_result(step, result)
                        db.commit()
            parent_status(run, steps); db.commit()
        elif operation == "clarify":
            if run.status != "needs_clarification" or steps:
                raise BusinessException("当前任务不需要补充描述", 409)
            query = run.query + "\n补充：" + payload["text"]
            if len(query) > 1000:
                raise BusinessException("合计描述不能超过1000字，请新建任务", 422)
            run.query = query; run.status = "planning"; run.message = None
            run.request = {k: v for k, v in run.request.items() if k != "plan"}
            db.commit()
        elif operation == "conditions":
            if run.status in {"cancelled", "completed"} or not any(s.spec["task_type"] == "reservation" for s in steps):
                raise BusinessException("当前任务不接受预约条件", 409)
            conditions = SpaceConditions.model_validate(payload["conditions"]).model_dump(mode="json")
            if run.conditions is not None and run.conditions != conditions:
                raise BusinessException("预约条件已绑定，修改条件请新建任务", 409)
            run.conditions = conditions
            if run.status == "needs_conditions":
                run.status = "ready"; run.message = "条件已绑定，请核对步骤后开始执行。"
            db.commit()
        elif operation == "cancel":
            for step in steps:
                if step.status in DONE:
                    continue
                result = invoke_specialist(db, user_id, step,
                    SpaceConditions.model_validate(run.conditions) if run.conditions else None, budget, "view")
                if result and result["status"] in CONFIRMATIONS:
                    result = invoke_specialist(db, user_id, step, None, budget, "decision",
                        {"action_id": result["action"]["id"], "confirmed": False})
                if result:
                    record_result(step, result)
                if step.status not in DONE:
                    step.status = "skipped"
                db.commit()
            run.status = "cancelled"; run.message = "已停止后续步骤；已提交的业务申请保留，请到对应业务页面处理。"; db.commit()
        elif operation == "retry":
            if run.status not in {"cancelled", "completed", "needs_conditions", "needs_clarification", "budget_exceeded"}:
                # This graph advances one phase per HTTP request. SQL owns parent progress;
                # each delegated agent owns its own LangGraph checkpoint namespace.
                class State(TypedDict):
                    phase: str
                graph = StateGraph(State)
                def plan(_):
                    plan_result = WorkflowPlan.model_validate(run.request["plan"]) if "plan" in run.request else plan_workflow(run.query, budget)
                    if plan_result.clarification:
                        run.status = "needs_clarification"; run.message = plan_result.clarification
                    else:
                        for position, task in enumerate(plan_result.steps):
                            db.add(WorkflowStep(workflow_id=workflow_id, position=position,
                                child_run_id=str(uuid5(NAMESPACE_URL, f"workflow:{workflow_id}:{position}")),
                                spec=task.model_dump()))
                        run.status = "needs_conditions" if not run.conditions and plan_result.steps[0].task_type == "reservation" else "ready"
                        run.message = "请明确填写并核对预约日期、时段、人数和用途。" if run.status == "needs_conditions" else "请核对计划，开始后仍需逐项选择和确认。"
                    db.commit()
                    return {}
                def delegate(_):
                    step = next(s for s in steps if s.status not in DONE)
                    if step.spec["task_type"] == "reservation" and not run.conditions:
                        run.status = "needs_conditions"; run.message = "请核对并确认预约日期、时段、人数和用途。"
                        db.commit()
                        return {}
                    step.status = "running"; db.commit()
                    result = invoke_specialist(db, user_id, step,
                        SpaceConditions.model_validate(run.conditions) if run.conditions else None, budget)
                    record_result(step, result); db.commit()
                    parent_status(run, steps); db.commit()
                    return {}
                graph.add_node("plan", plan); graph.add_node("specialist", delegate)
                graph.add_conditional_edges(START, lambda s: s["phase"])
                graph.add_edge("plan", END); graph.add_edge("specialist", END)
                graph.compile().invoke({"phase": "specialist" if steps else "plan"})
        else:
            step = next((s for s in steps if s.id == payload.get("step_id")), None)
            if step is None:
                raise BusinessException("步骤不属于此任务", 404)
            current = next((s for s in steps if s.status not in DONE), None)
            replay = step.status == "completed" and (operation == "decision" or
                (step.spec["read_only"] and operation in {"loans_page", "spaces_page"}))
            if run.status == "cancelled" or (step != current and not replay):
                raise BusinessException("请按顺序操作当前步骤", 409)
            if operation == "skip":
                result = invoke_specialist(db, user_id, step,
                    SpaceConditions.model_validate(run.conditions) if run.conditions else None, budget, "view")
                if result and result["status"] in CONFIRMATIONS:
                    result = invoke_specialist(db, user_id, step, None, budget, "decision",
                        {"action_id": result["action"]["id"], "confirmed": False})
                    record_result(step, result)
                if result and result["status"] in RECEIPTS:
                    record_result(step, result)
                else:
                    step.status = "skipped"
            else:
                result = invoke_specialist(db, user_id, step,
                    SpaceConditions.model_validate(run.conditions) if run.conditions else None, budget,
                    operation, {k: v for k, v in payload.items() if k != "step_id"})
                record_result(step, result)
            db.commit(); parent_status(run, steps); db.commit()
    except (BudgetExceeded, BusinessException) as exc:
        db.rollback()
        if isinstance(exc, BusinessException) and (operation != "retry" or exc.code not in {429, 502, 503}):
            raise
        run = owned(db, user_id, workflow_id)
        steps = steps_for(db, workflow_id)
        if isinstance(exc, BudgetExceeded) or (isinstance(exc, BusinessException) and exc.code == 429):
            run.status = "budget_exceeded"; run.message = "任务已达到执行预算，请查看已有结果或停止任务。"
        else:
            for step in steps:
                if step.status == "running":
                    step.status = "failed"
            run.status = "partial_failure" if any(s.status == "completed" for s in steps) else "retryable"
            run.message = exc.message
        db.commit()
    except Exception:
        db.rollback()
        run = owned(db, user_id, workflow_id)
        run.status = "partial_failure" if any(s.status == "completed" for s in steps_for(db, workflow_id)) else "retryable"
        run.message = "任务暂未完成，请刷新状态后重试；已有申请不会自动撤回。"; db.commit()
    finally:
        db.rollback()
        elapsed = time.monotonic() - started if operation not in {"view", "conditions", "clarify"} else 0
        db.execute(update(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.lease_token == token).values(lease_token=None, lease_until=None,
                active_seconds=WorkflowRun.active_seconds + elapsed))
        db.commit()
    return view(db, owned(db, user_id, workflow_id))
