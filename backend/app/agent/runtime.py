"""Authenticated orchestration, durable checkpoints and per-run execution leases."""

from datetime import datetime, timedelta
import logging
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.agent.actions import decide_borrow, prepare_borrow
from app.agent.graph import build_graph
from app.agent.policy import RunBudget
from app.agent.tools import execute_read_tool, tool_definitions
from app.common.exceptions import BusinessException
from app.config import settings
from app.models.agent import AgentRun
from app.services.ai_services import _create_chat_model


logger = logging.getLogger(__name__)


def call_model(messages, budget):
    from langsmith import tracing_context
    budget.consume("model")
    model = _create_chat_model(max_retries=0, max_tokens=512).model_copy(
        update={"request_timeout": min(20, budget.remaining())})
    with tracing_context(enabled=False):
        result = model.bind_tools(tool_definitions()).invoke(messages)
    budget.remaining()
    return result


def owned_run(db, user_id, run_id):
    run = db.query(AgentRun).filter_by(run_id=run_id, user_id=user_id).first()
    if run is None:
        raise BusinessException("任务不存在", 404)
    if run.expires_at <= datetime.now():
        raise BusinessException("任务已过期，请重新查找", 409)
    return run


def start_run(db, user_id, request_id, query):
    run = db.query(AgentRun).filter_by(run_id=request_id).first()
    if run is not None:
        owned_run(db, user_id, request_id)
        if run.query != query:
            raise BusinessException("任务编号已用于其他问题，请新建查找", 409)
    else:
        db.add(AgentRun(run_id=request_id, user_id=user_id, query=query,
            expires_at=datetime.now() + timedelta(hours=24)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            run = owned_run(db, user_id, request_id)
            if run.query != query:
                raise BusinessException("任务内容冲突", 409)
    return run_graph(db, user_id, request_id, "retry")


def graph_view(run_id, snapshot):
    for task in snapshot.tasks:
        if task.interrupts:
            value = task.interrupts[0].value
            return {"run_id": run_id, "status": value["kind"], **{k: v for k, v in value.items() if k != "kind"}}
    state = snapshot.values
    return {"run_id": run_id, "status": state.get("status", "retryable"),
            "message": state.get("message", "任务尚未完成，可重试继续。"),
            "receipt": state.get("receipt"), "action": state.get("action")}


def run_graph(db, user_id, run_id, operation="view", payload=None):
    run = owned_run(db, user_id, run_id)
    query = run.query
    token = str(uuid4())
    now = datetime.now()
    acquired = db.execute(update(AgentRun).where(AgentRun.run_id == run_id,
        or_(AgentRun.lease_until.is_(None), AgentRun.lease_until < now)).values(
            lease_token=token, lease_until=now + timedelta(minutes=3))).rowcount
    db.commit()
    if not acquired:
        raise BusinessException("任务正在处理中，请稍后刷新", 409)
    budget = RunBudget()
    try:
        settings.AGENT_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SqliteSaver.from_conn_string(str(settings.AGENT_CHECKPOINT_PATH)) as saver:
            def read(name, args):
                try:
                    if settings.AGENT_TOOL_TRANSPORT == "mcp":
                        from app.agent.mcp_adapter import read_tool
                        return read_tool(user_id, name, args, budget)
                    return execute_read_tool(db, user_id, name, args, budget)
                finally:
                    db.rollback()

            def execute(action_id, confirmed):
                if settings.AGENT_TOOL_TRANSPORT == "mcp":
                    from app.agent.mcp_adapter import submit_decision
                    return submit_decision(user_id, action_id, confirmed)
                return decide_borrow(db, user_id, action_id, confirmed)

            graph = build_graph(saver, lambda messages: call_model(messages, budget),
                read,
                prepare=lambda book_id: prepare_borrow(db, user_id, run_id, book_id),
                execute=execute)
            config = {"configurable": {"thread_id": run_id}, "recursion_limit": 24}
            snapshot = graph.get_state(config)
            view = graph_view(run_id, snapshot)
            if operation == "view":
                return view
            if operation == "select":
                if view["status"] != "select_book":
                    if (view.get("action") or {}).get("book", {}).get("id") == payload["book_id"]:
                        return view
                    raise BusinessException("当前任务不允许选择书目，请刷新", 409)
                if payload["book_id"] not in {b["id"] for b in view["books"]}:
                    raise BusinessException("请选择本次查找返回的书目", 409)
                inputs = Command(resume=payload)
            elif operation == "decision":
                action = view.get("action") or {}
                if action.get("id") != payload["action_id"]:
                    raise BusinessException("确认内容不匹配", 409)
                if view["status"] in {"pending", "cancelled"}:
                    expected = view["status"] == "pending"
                    if payload["confirmed"] != expected:
                        raise BusinessException("操作已完成，请查看我的借阅", 409)
                    return view
                if view["status"] != "confirm_borrow":
                    raise BusinessException("任务尚未到确认阶段，请刷新", 409)
                inputs = Command(resume=payload)
            else:
                if any(task.interrupts for task in snapshot.tasks) or (snapshot.values and not snapshot.next):
                    return view
                inputs = None if snapshot.values else {"query": query, "books": [], "messages": [], "model_calls": 0, "tool_calls": 0}
            graph.invoke(inputs, config)
            return graph_view(run_id, graph.get_state(config))
    except BusinessException:
        raise
    except Exception:
        raise BusinessException("借阅助手暂时未完成操作，请刷新任务状态后重试；不要重复创建申请。", 503) from None
    finally:
        db.rollback()
        db.execute(update(AgentRun).where(AgentRun.run_id == run_id, AgentRun.lease_token == token).values(lease_token=None, lease_until=None))
        db.commit()
        logger.info("agent_run run_id=%s operation=%s model_calls=%s tool_calls=%s", run_id, operation, budget.models, budget.tools)
