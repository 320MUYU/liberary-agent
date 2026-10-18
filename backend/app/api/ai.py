from fastapi import APIRouter, Depends

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.schemas.ai import ChatRequest
from app.services import ai_services


router = APIRouter(prefix="/ai", tags=["AI 对话接口"])


def get_chat_db(data: ChatRequest):
    yield from get_db()


@router.post("/chat")
def chat(
    data: ChatRequest,
    user: User = Depends(get_current_user),
    db=Depends(get_chat_db),
):
    message = ai_services.chat(data, db=db, user_id=user.id)
    # Legacy clients receive the original shape; explicit knowledge mode adds evidence.
    exclude = {"sources", "retrieval_status"} if data.mode == "chat" else set()
    return Response.success(data=message.model_dump(exclude=exclude))
