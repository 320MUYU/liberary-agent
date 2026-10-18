"""One durable conversation coordinates independent, bounded business workflows."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.agent import workflow
from app.agent.coordinator import route_conversation
from app.common.exceptions import BusinessException
from app.models.conversation import Conversation, ConversationTurn
from app.models.users import User
from app.models.workflow import WorkflowRun
from app.schemas.conversation import ConversationDecision
from app.services.time_context import resolve_date_expression


def owned(db, user_id, conversation_id):
    row = db.query(Conversation).filter_by(conversation_id=conversation_id, user_id=user_id).first()
    if row is None:
        raise BusinessException("对话不存在", 404)
    user = db.get(User, user_id)
    if user is None or user.status != 1:
        raise BusinessException("账号不可用", 403)
    return row


def turns_for(db, conversation_id):
    return db.query(ConversationTurn).filter_by(conversation_id=conversation_id).populate_existing().order_by(ConversationTurn.id).all()


def create(db, user_id, request_id):
    if db.query(Conversation).filter_by(conversation_id=request_id).first() is None:
        db.add(Conversation(conversation_id=request_id, user_id=user_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return view(db, user_id, request_id)


@contextmanager
def leased(db, user_id, conversation_id):
    owned(db, user_id, conversation_id)
    token = str(uuid4()); now = datetime.now()
    acquired = db.execute(update(Conversation).where(Conversation.conversation_id == conversation_id,
        or_(Conversation.lease_until.is_(None), Conversation.lease_until < now)).values(
            lease_token=token, lease_until=now + timedelta(minutes=4))).rowcount
    db.commit()
    if not acquired:
        raise BusinessException("当前对话正在处理请求，请稍后刷新", 409)
    try:
        yield
    finally:
        db.rollback()
        db.execute(update(Conversation).where(Conversation.conversation_id == conversation_id,
            Conversation.lease_token == token).values(lease_token=None, lease_until=None))
        db.commit()


def task_owned(db, user_id, conversation_id, workflow_id):
    owned(db, user_id, conversation_id)
    attached = db.query(ConversationTurn).filter_by(conversation_id=conversation_id, workflow_id=workflow_id).first()
    if attached is None:
        raise BusinessException("任务不属于当前对话", 404)
    return workflow.owned(db, user_id, workflow_id)


def view(db, user_id, conversation_id, *, refresh=True):
    owned(db, user_id, conversation_id)
    turns = turns_for(db, conversation_id)
    tasks = []
    for task_id in dict.fromkeys(turn.workflow_id for turn in turns if turn.workflow_id):
        row = db.query(WorkflowRun).filter_by(workflow_id=task_id, user_id=user_id).first()
        if row is None:
            continue
        task = workflow.view(db, row)
        if row.expires_at <= datetime.now():
            task["status"] = "expired"
            task["message"] = "此任务已过期，历史结果保留，请发送新需求。"
        elif refresh:
            try:
                task = workflow.operate(db, user_id, task_id)
            except BusinessException as exc:
                task["refresh_error"] = exc.message
        task["draft_conditions"] = row.request.get("draft_conditions", {})
        tasks.append(task)
    return {"conversation_id": conversation_id, "turns": [{"request_id": turn.request_id,
        "text": turn.request["text"], "hint": turn.request.get("hint", "auto"), "status": turn.status,
        "reply": turn.reply, "workflow_id": turn.workflow_id} for turn in turns], "tasks": tasks}


def history_for(turns):
    history = []
    for turn in turns:
        if turn.status != "completed":
            continue
        history.append({"role": "user", "content": turn.request["text"]})
        if turn.reply:
            history.append({"role": "assistant", "content": turn.reply["content"][:2000]})
    selected = []; remaining = 8000
    for message in reversed(history[-16:]):
        content = message["content"][-remaining:]
        if not content:
            break
        selected.append({**message, "content": content})
        remaining -= len(content)
    return list(reversed(selected))


def routing_tasks(tasks):
    # Resource lists stay ordered so references such as "第二本" remain meaningful.
    selected = tasks[-5:]
    return [{"workflow_id": task["workflow_id"], "status": task["status"], "query": task["query"],
        "draft_conditions": task.get("draft_conditions"), "conditions": task.get("conditions"),
        "steps": [{"title": step["spec"]["title"], "status": step["status"],
            "result": {key: value for key, value in (step["result"] or {}).items()
                if key in {"status", "content", "books", "loans", "spaces", "conditions", "message"}}}
            for step in task["steps"]]} for task in selected]


def save_draft(db, run, draft):
    if draft is None:
        return
    values = {**run.request.get("draft_conditions", {}), **draft.model_dump(exclude_none=True)}
    if draft.date_expression is not None:
        resolved = resolve_date_expression(draft.date_expression)
        values.pop("date", None)
        values["date_candidates"] = resolved["candidates"]
        values["date_message"] = resolved["message"]
        if resolved["status"] == "resolved":
            values["date"] = resolved["date"]
    run.request = {**run.request, "draft_conditions": values}
    db.commit()


def send(db, user_id, conversation_id, message):
    request = message.model_dump(mode="json", exclude={"request_id"})
    request_id = str(message.request_id)
    with leased(db, user_id, conversation_id):
        turn = db.query(ConversationTurn).filter_by(conversation_id=conversation_id, request_id=request_id).first()
        if turn is not None and turn.request != request:
            raise BusinessException("消息编号已绑定其他内容", 409)
        if turn is not None and turn.status == "completed":
            return view(db, user_id, conversation_id, refresh=False)
        if turn is None:
            if len(turns_for(db, conversation_id)) >= 100:
                raise BusinessException("此对话已达100轮，请新建对话", 409)
            turn = ConversationTurn(conversation_id=conversation_id, request_id=request_id, request=request)
            db.add(turn); db.commit()
        turn.status = "processing"; turn.reply = None; db.commit()
        try:
            history = history_for(turns_for(db, conversation_id))
            if turn.decision is None:
                tasks = view(db, user_id, conversation_id, refresh=False)["tasks"]
                decision = route_conversation(message.text, history, routing_tasks(tasks), message.hint)
                turn.decision = decision.model_dump(mode="json"); db.commit()
            decision = ConversationDecision.model_validate(turn.decision)
            if decision.action == "ask":
                reply = decision.message
            elif decision.action == "plan":
                task_id = str(uuid5(NAMESPACE_URL, f"conversation:{conversation_id}:{request_id}"))
                turn.workflow_id = task_id; db.commit()
                run = db.query(WorkflowRun).filter_by(workflow_id=task_id, user_id=user_id).first()
                if run is None:
                    workflow.create_workflow(db, user_id, task_id, message.text,
                        plan=decision.plan.model_dump(), context=history)
                    run = workflow.owned(db, user_id, task_id)
                save_draft(db, run, decision.draft)
                if run.status in {"planning", "ready"}:
                    workflow.operate(db, user_id, task_id, "retry")
                reply = "已按你的需求安排处理步骤，结果与后续操作见下方。"
            else:
                task_id = str(decision.workflow_id)
                run = task_owned(db, user_id, conversation_id, task_id)
                if decision.action == "conditions":
                    if run.status != "needs_conditions":
                        raise BusinessException("此任务当前不需要补充预约条件", 409)
                    save_draft(db, run, decision.draft)
                    reply = "已补充预约条件，请在原任务卡片中核对并确认查询条件。"
                else:
                    workflow.operate(db, user_id, task_id, "clarify", {"text": decision.message})
                    workflow.operate(db, user_id, task_id, "retry")
                    reply = "已补充原任务的需求，请查看更新后的任务卡片。"
            turn.reply = {"content": reply}
            turn.status = "completed"; db.commit()
        except Exception as exc:
            db.rollback()
            turn.status = "failed"
            turn.reply = {"content": exc.message if isinstance(exc, BusinessException) else "请求未完成，请刷新后重试。"}
            db.commit()
            if isinstance(exc, BusinessException):
                raise
            raise BusinessException("请求未完成，请刷新后重试。", 503) from None
    return view(db, user_id, conversation_id, refresh=False)


def operate_task(db, user_id, conversation_id, task_id, operation, payload=None):
    with leased(db, user_id, conversation_id):
        task_owned(db, user_id, conversation_id, task_id)
        workflow.operate(db, user_id, task_id, operation, payload)
    return view(db, user_id, conversation_id, refresh=False)
