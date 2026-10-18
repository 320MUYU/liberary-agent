"""Authenticated orchestration, durable checkpoints and per-run execution leases."""

from datetime import datetime, timedelta
import logging
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.agent.actions import decide_borrow, prepare_borrow, decide_return, prepare_return
from app.agent.reservation_actions import draft_action, prepare_reservation, decide_reservation, receipt as reservation_receipt
from app.agent.graph import build_graph
from app.agent.policy import RunBudget, BudgetExceeded
from app.agent.tools import execute_read_tool, tool_definitions, allowed_tools, public_loan, error
from app.common.exceptions import BusinessException
from app.config import settings
from app.models.agent import AgentRun, AgentReservationAction
from app.services.space_discovery import SpaceConditions, get_space
from app.services.book_discovery import refresh_books
from app.services.ai_services import _create_chat_model
from app.services import loan_service
from app.models.users import User


logger = logging.getLogger(__name__)


def call_model(messages, budget, task_type="borrow"):
    from langsmith import tracing_context
    budget.consume("model")
    model = _create_chat_model(max_retries=0, max_tokens=512).model_copy(
        update={"request_timeout": min(20, budget.remaining())})
    with tracing_context(enabled=False):
        result = model.bind_tools(tool_definitions(task_type)).invoke(messages)
    budget.remaining()
    return result


def owned_run(db, user_id, run_id):
    run = db.query(AgentRun).filter_by(run_id=run_id, user_id=user_id).first()
    if run is None:
        raise BusinessException("任务不存在", 404)
    if run.expires_at <= datetime.now():
        raise BusinessException("任务已过期，请重新查找", 409)
    return run


def start_run(db, user_id, request_id, query, task_type="borrow", conditions=None, *, budget=None, context=None):
    if task_type not in {"borrow", "my_loans", "return", "reservation"}:
        raise BusinessException("不支持的任务类型", 422)
    if task_type == "reservation":
        conditions = SpaceConditions.model_validate(conditions)
    run = db.query(AgentRun).filter_by(run_id=request_id).first()
    if run is not None:
        owned_run(db, user_id, request_id)
        if run.query != query or run.task_type != task_type:
            raise BusinessException("任务编号已用于其他问题，请新建查找", 409)
    else:
        db.add(AgentRun(run_id=request_id, user_id=user_id, query=query, task_type=task_type,
            expires_at=datetime.now() + timedelta(hours=24)))
        if task_type == "reservation":
            db.add(draft_action(user_id, request_id, conditions))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            run = owned_run(db, user_id, request_id)
            if run.query != query or run.task_type != task_type:
                raise BusinessException("任务内容冲突", 409)
    if task_type == "reservation":
        action = db.query(AgentReservationAction).filter_by(run_id=request_id, user_id=user_id).first()
        if action is None or action.conditions != conditions.model_dump(mode="json"):
            raise BusinessException("任务编号已绑定其他预约条件", 409)
    return run_graph(db, user_id, request_id, "retry", budget=budget, context=context)


def graph_view(run_id, snapshot, db=None, user_id=None):
    for task in snapshot.tasks:
        if task.interrupts:
            value = dict(task.interrupts[0].value)
            if value["kind"] == "select_book" and db is not None:
                value["books"] = refresh_books(db, value["books"])
            if value["kind"] == "select_space" and db is not None:
                db.rollback()
                page = snapshot.values.get("space_page", value)
                conditions = SpaceConditions.model_validate(snapshot.values["conditions"])
                rooms = []
                checked_at = page.get("checked_at")
                for room in page["spaces"]:
                    try:
                        fresh = get_space(db, conditions, room["id"])
                        rooms.extend(fresh["spaces"])
                        checked_at = fresh["checked_at"]
                    except BusinessException as exc:
                        if exc.code != 404:
                            raise
                value.update({key: val for key, val in page.items() if key not in {"kind", "spaces"}})
                value.update(spaces=rooms, checked_at=checked_at)
            if value["kind"] == "select_loan" and db is not None:
                db.rollback()
                user = db.get(User, user_id)
                loans = []
                for loan in snapshot.values.get("loans", value["loans"]):
                    try:
                        loans.append(public_loan(loan_service.get_my_loan(db, user, loan["id"])))
                    except BusinessException as exc:
                        if exc.code != 404:
                            raise
                value.update(loans=loans, loan_page={**snapshot.values.get("loan_page", value["loan_page"]), "loans": loans})
            return {"run_id": run_id, "status": value["kind"], **{k: v for k, v in value.items() if k != "kind"}}
    state = snapshot.values
    if db is not None and state.get("task_type") == "reservation" and state.get("receipt", {}).get("reservation_id"):
        db.rollback()
        receipt = reservation_receipt(db, user_id, state["receipt"]["reservation_id"])
        return {"run_id": run_id, "status": receipt["status"], "receipt": receipt,
            "action": state.get("action"), "message": receipt["message"]}
    if db is not None and state.get("task_type", "borrow") != "borrow" and state.get("status") in {"return_pending", "returned"}:
        db.rollback()
        user = db.get(User, user_id)
        current = loan_service.get_my_loan(db, user, state["receipt"]["loan_id"])
        # No write is needed to show an administrator's later confirmation.
        receipt = {"status": current.status, "loan_id": current.id, "loan": public_loan(current),
            "message": "管理员已确认归还。" if current.status == "returned" else "归还申请已提交，请交还实体图书，待管理员确认归还。"}
        return {"run_id": run_id, "status": receipt["status"], "receipt": receipt, "action": state.get("action"), "message": receipt["message"]}
    return {"run_id": run_id, "status": state.get("status", "retryable"),
            "message": state.get("message", "任务尚未完成，可重试继续。"),
            "degraded": state.get("degraded", []),
            "receipt": state.get("receipt"), "action": state.get("action")}


def run_graph(db, user_id, run_id, operation="view", payload=None, *, budget=None, context=None):
    if budget is None:
        from app.models.workflow import WorkflowStep
        if db.query(WorkflowStep.id).filter_by(child_run_id=run_id).first():
            raise BusinessException("请从组合任务入口操作此子任务", 409)
    run = owned_run(db, user_id, run_id)
    query = run.query
    task_type = run.task_type
    conditions = None
    if task_type == "reservation":
        action = db.query(AgentReservationAction).filter_by(run_id=run_id, user_id=user_id).first()
        if action is None:
            raise BusinessException("预约任务缺少条件，请重新查询", 409)
        conditions = SpaceConditions.model_validate(action.conditions)
    token = str(uuid4())
    now = datetime.now()
    acquired = db.execute(update(AgentRun).where(AgentRun.run_id == run_id,
        or_(AgentRun.lease_until.is_(None), AgentRun.lease_until < now)).values(
            lease_token=token, lease_until=now + timedelta(minutes=3))).rowcount
    db.commit()
    if not acquired:
        raise BusinessException("任务正在处理中，请稍后刷新", 409)
    budget = budget if budget is not None else RunBudget()
    try:
        settings.AGENT_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SqliteSaver.from_conn_string(str(settings.AGENT_CHECKPOINT_PATH)) as saver:
            def read(name, args):
                try:
                    if name not in allowed_tools(task_type):
                        budget.consume("tool")
                        return error("tool_not_allowed", "当前任务不支持该工具")
                    if task_type == "reservation":
                        args = dict(args)
                        if "conditions" in args and SpaceConditions.model_validate(args["conditions"]) != conditions:
                            budget.consume("tool")
                            return error("invalid_conditions", "模型不能改变已确认预约条件")
                        args["conditions"] = conditions.model_dump(mode="json")
                    if settings.AGENT_TOOL_TRANSPORT == "mcp":
                        from app.agent.mcp_adapter import read_tool
                        return read_tool(user_id, name, args, budget)
                    return execute_read_tool(db, user_id, name, args, budget)
                finally:
                    db.rollback()

            def execute(action_id, confirmed):
                if settings.AGENT_TOOL_TRANSPORT == "mcp":
                    from app.agent.mcp_adapter import submit_decision
                    return submit_decision(user_id, action_id, confirmed, action_type=("reservation" if task_type == "reservation" else ("borrow" if task_type == "borrow" else "return")))
                handler = decide_reservation if task_type == "reservation" else (decide_borrow if task_type == "borrow" else decide_return)
                return handler(db, user_id, action_id, confirmed)

            graph = build_graph(saver, lambda messages: call_model(messages, budget) if task_type == "borrow" else call_model(messages, budget, task_type),
                read,
                prepare=lambda book_id: prepare_borrow(db, user_id, run_id, book_id),
                execute=execute, prepare_return=lambda loan_id: prepare_return(db, user_id, run_id, loan_id),
                prepare_reservation=lambda space_id: prepare_reservation(db, user_id, run_id, space_id, conditions))
            config = {"configurable": {"thread_id": run_id}, "recursion_limit": 24}
            snapshot = graph.get_state(config)
            def current_view():
                return {**graph_view(run_id, graph.get_state(config), db, user_id), "task_type": task_type,
                    **({"conditions": conditions.model_dump(mode="json")} if conditions is not None else {})}
            view = current_view()
            if operation == "view":
                return view
            if operation == "select":
                if task_type != "borrow":
                    raise BusinessException("请在本任务中选择借阅记录", 409)
                if view["status"] != "select_book":
                    if (view.get("action") or {}).get("book", {}).get("id") == payload["book_id"]:
                        return view
                    raise BusinessException("当前任务不允许选择书目，请刷新", 409)
                if payload["book_id"] not in {b["id"] for b in view["books"]}:
                    raise BusinessException("请选择本次查找返回的书目", 409)
                inputs = Command(resume=payload)
            elif operation in {"spaces_page", "select_space"}:
                if task_type != "reservation":
                    raise BusinessException("当前任务不支持空间操作", 409)
                if view["status"] != "select_space":
                    if operation == "select_space" and (view.get("action") or {}).get("space", {}).get("id") == payload["space_id"]:
                        return view
                    raise BusinessException("当前任务不允许选择或翻页，请刷新", 409)
                if operation == "spaces_page":
                    result = read("search_spaces", {"page": payload["page"], "keyword": view.get("keyword", "")})
                    if not result.get("ok"):
                        raise BusinessException("空间查询暂不可用", 503)
                    graph.update_state(config, {"spaces": result["data"]["spaces"], "space_page": result["data"], "pending_tools": []}, as_node="think")
                    graph.invoke(None, config)
                    return current_view()
                if payload["space_id"] not in {room["id"] for room in view["spaces"] if room["can_reserve"]}:
                    raise BusinessException("请选择本页可申请的空间", 409)
                inputs = Command(resume=payload)
            elif operation == "loans_page":
                if task_type == "borrow" or view["status"] != "select_loan":
                    raise BusinessException("当前任务不允许翻页，请刷新", 409)
                filters = view.get("loan_page", {})
                result = read("list_my_loans", {"page": payload["page"],
                    "status": filters.get("status"), "keyword": filters.get("keyword", "")})
                if not result.get("ok"):
                    raise BusinessException(result.get("message", "借阅查询暂不可用"), 503)
                graph.update_state(config, {"loans": result["data"]["loans"], "loan_page": result["data"],
                    "pending_tools": []}, as_node="think")
                graph.invoke(None, config)
                return current_view()
            elif operation == "select_loan":
                if task_type == "borrow":
                    raise BusinessException("当前任务不允许选择借阅记录", 409)
                if view["status"] != "select_loan":
                    if (view.get("action") or {}).get("loan", {}).get("id") == payload["loan_id"]:
                        return view
                    raise BusinessException("当前任务不允许选择记录，请刷新", 409)
                if payload["loan_id"] not in {l["id"] for l in view["loans"] if l["status"] == "borrowed"}:
                    raise BusinessException("请选择本页借阅中的记录", 409)
                inputs = Command(resume=payload)
            elif operation == "decision":
                action = view.get("action") or {}
                if action.get("id") != payload["action_id"]:
                    raise BusinessException("确认内容不匹配", 409)
                if view["status"] in {"pending", "return_pending", "returned", "cancelled", "reservation_pending", "reservation_approved", "reservation_rejected", "reservation_cancelled"}:
                    expected = view["status"] != "cancelled"
                    if payload["confirmed"] != expected:
                        raise BusinessException("操作已完成，请查看我的借阅", 409)
                    return view
                expected_status = "confirm_reservation" if task_type == "reservation" else ("confirm_borrow" if task_type == "borrow" else "confirm_return")
                if view["status"] != expected_status:
                    raise BusinessException("任务尚未到确认阶段，请刷新", 409)
                inputs = Command(resume=payload)
            else:
                if any(task.interrupts for task in snapshot.tasks) or (snapshot.values and not snapshot.next):
                    return view
                inputs = None if snapshot.values else {"query": query, "task_type": task_type, "books": [], "messages": [], "model_calls": 0, "tool_calls": 0}
                if inputs is not None and context:
                    inputs["context"] = context
                if inputs is not None and conditions is not None:
                    inputs["conditions"] = conditions.model_dump(mode="json")
            graph.invoke(inputs, config)
            return current_view()
    except BudgetExceeded:
        raise BusinessException("本次执行已达到预算上限，请查看已有结果", 429) from None
    except BusinessException:
        raise
    except Exception:
        raise BusinessException("借阅助手暂时未完成操作，请刷新任务状态后重试；不要重复创建申请。", 503) from None
    finally:
        db.rollback()
        db.execute(update(AgentRun).where(AgentRun.run_id == run_id, AgentRun.lease_token == token).values(lease_token=None, lease_until=None))
        db.commit()
        logger.info("agent_run run_id=%s operation=%s model_calls=%s tool_calls=%s", run_id, operation, budget.models, budget.tools)
