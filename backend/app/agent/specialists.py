"""Each specialist owns an independent durable child graph and scoped tool context."""

from app.agent import runtime
from app.common.exceptions import BusinessException
from app.models.agent import AgentRun
from app.schemas.workflow import WorkflowTask
from app.schemas.ai import ChatRequest
from app.models.workflow import WorkflowRun, WorkflowStep
from app.services import ai_services, rag_service
import json


SPECIALISTS = {"borrow": "library", "my_loans": "library", "return": "library", "reservation": "space"}
SPECIALISTS.update({"chat": "conversation", "knowledge": "knowledge", "space_query": "space"})


def context_for(db, step):
    if not getattr(step, "workflow_id", None):
        return []
    parent = db.query(WorkflowRun).filter_by(workflow_id=step.workflow_id).one()
    context = list(parent.request.get("context", []))[-8:]
    previous = db.query(WorkflowStep).filter(WorkflowStep.workflow_id == step.workflow_id,
        WorkflowStep.position < step.position, WorkflowStep.status == "completed").order_by(WorkflowStep.position).all()
    for earlier in previous:
        result = earlier.result or {}
        useful = {key: result[key] for key in ("content", "sources", "books", "spaces", "conditions", "receipt") if key in result}
        content = json.dumps({"previous_step": earlier.spec["title"], "data": useful}, ensure_ascii=False)
        context.append({"role": "assistant", "content": content[:4000]})
    return context[-10:]


def invoke_specialist(db, user_id, step, conditions, budget, operation="retry", payload=None):
    task = WorkflowTask.model_validate(step.spec)
    if task.read_only and operation not in {"view", "retry", "loans_page", "spaces_page"}:
        raise BusinessException("此步骤只查询，不接受业务操作", 409)
    if task.task_type in {"chat", "knowledge", "space_query"}:
        if operation == "view" or getattr(step, "result", None):
            return getattr(step, "result", None)
        if operation != "retry":
            raise BusinessException("回答步骤不接受业务操作", 409)
        context = context_for(db, step)
        original_question = None
        if task.task_type == "knowledge" and getattr(step, "workflow_id", None):
            parent = db.query(WorkflowRun).filter_by(workflow_id=step.workflow_id).one()
            original_question = parent.query
        data = ChatRequest(mode="knowledge" if task.task_type == "knowledge" else "chat",
            messages=context + [{"role": "user", "content": task.query}])
        if task.task_type == "knowledge":
            response = rag_service.knowledge_chat(data, db, budget=budget, original_question=original_question)
        else:
            response = ai_services.chat(data, db=db, user_id=user_id, budget=budget, unified=True)
        return {"run_id": step.child_run_id, "status": "answered", "task_type": task.task_type,
            **response.model_dump()}
    existing = db.query(AgentRun).filter_by(run_id=step.child_run_id, user_id=user_id).first()
    if existing is None:
        if operation not in {"retry", "view"}:
            raise BusinessException("子任务尚未开始", 409)
        if operation == "view":
            return None
        context = context_for(db, step)
        return runtime.start_run(db, user_id, step.child_run_id, task.query, task.task_type,
            conditions=conditions if task.task_type == "reservation" else None, budget=budget,
            **({"context": context} if context else {}))
    return runtime.run_graph(db, user_id, step.child_run_id, operation, payload, budget=budget)
