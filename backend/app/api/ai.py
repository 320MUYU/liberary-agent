from fastapi import APIRouter, Depends

from app.common.response import Response
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.schemas.ai import ChatRequest
from app.services import ai_services


router = APIRouter(prefix="/ai", tags=["AI 对话接口"])


@router.post("/chat")
def chat(
    data: ChatRequest,
    _: User = Depends(get_current_user),
):
    message = ai_services.chat(data)
    return Response.success(data=message)
