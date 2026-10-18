"""Each specialist owns an independent durable child graph and scoped tool context."""

from app.agent import runtime
from app.common.exceptions import BusinessException
from app.models.agent import AgentRun
from app.schemas.workflow import WorkflowTask


SPECIALISTS = {"borrow": "library", "my_loans": "library", "return": "library", "reservation": "space"}
SPECIALISTS.update({"chat": "conversation", "knowledge": "knowledge", "space_query": "space"})


def invoke_specialist(db, user_id, step, conditions, budget, operation="retry", payload=None):
    task = WorkflowTask.model_validate(step.spec)
    if task.read_only and operation not in {"view", "retry", "loans_page", "spaces_page"}:
        raise BusinessException("此步骤只查询，不接受业务操作", 409)
    existing = db.query(AgentRun).filter_by(run_id=step.child_run_id, user_id=user_id).first()
    if existing is None:
        if operation not in {"retry", "view"}:
            raise BusinessException("子任务尚未开始", 409)
        if operation == "view":
            return None
        return runtime.start_run(db, user_id, step.child_run_id, task.query, task.task_type,
            conditions=conditions if task.task_type == "reservation" else None, budget=budget)
    return runtime.run_graph(db, user_id, step.child_run_id, operation, payload, budget=budget)
