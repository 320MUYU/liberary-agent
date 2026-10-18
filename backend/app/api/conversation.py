"""One authenticated entry for messages and task cards in the same conversation."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.agent import conversation
from app.api.workflow import ConditionsRequest, ClarifyRequest, StepRequest
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.conversation import CreateConversation, SendMessage


router = APIRouter(prefix="/conversations", tags=["统一 AI 会话"])


@router.post("")
def create(data: CreateConversation, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=conversation.create(db, user.id, str(data.request_id)))


@router.get("/{conversation_id}")
def view(conversation_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=conversation.view(db, user.id, str(conversation_id)))


@router.post("/{conversation_id}/messages")
def send(conversation_id: UUID, data: SendMessage, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=conversation.send(db, user.id, str(conversation_id), data))


@router.post("/{conversation_id}/tasks/{task_id}/retry")
def retry(conversation_id: UUID, task_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=conversation.operate_task(db, user.id, str(conversation_id), str(task_id), "retry"))


@router.post("/{conversation_id}/tasks/{task_id}/cancel")
def cancel(conversation_id: UUID, task_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=conversation.operate_task(db, user.id, str(conversation_id), str(task_id), "cancel"))


@router.post("/{conversation_id}/tasks/{task_id}/conditions")
def conditions(conversation_id: UUID, task_id: UUID, data: ConditionsRequest,
        user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=conversation.operate_task(db, user.id, str(conversation_id), str(task_id),
        "conditions", data.model_dump(mode="json")))


@router.post("/{conversation_id}/tasks/{task_id}/clarify")
def clarify(conversation_id: UUID, task_id: UUID, data: ClarifyRequest,
        user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=conversation.operate_task(db, user.id, str(conversation_id), str(task_id),
        "clarify", data.model_dump()))


@router.post("/{conversation_id}/tasks/{task_id}/steps")
def step(conversation_id: UUID, task_id: UUID, data: StepRequest,
        user=Depends(get_current_user), db=Depends(get_db)):
    payload = data.model_dump(mode="json", exclude_unset=True)
    operation = payload.pop("operation")
    return Response.success(data=conversation.operate_task(db, user.id, str(conversation_id), str(task_id), operation, payload))
