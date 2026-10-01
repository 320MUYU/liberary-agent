from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_deepseek import ChatDeepSeek

from app.common.exceptions import BusinessException
from app.config import settings
from app.schemas.ai import ChatRequest, ChatResponse


SYSTEM_PROMPT = """你是智能实验室预约系统的 AI 助手，回答要准确、简洁。
你可以介绍本系统的预约流程：
1. 登录后打开实验室列表，选择实验室或设备。
2. 填写日期、时段和实验用途后提交，预约状态变为待审核。
3. 管理员审核通过后，用户可以按预约时段使用实验室。
4. 用户可以在系统允许的时间范围内取消自己的待审核或已通过预约。

你目前不能直接读取实时实验室、设备和预约数据，也不能替用户提交或修改预约。
遇到需要实时数据的问题，请引导用户前往对应页面查看，不要编造实验室、设备、空闲时段或预约结果。"""


@lru_cache
def get_chat_model() -> ChatDeepSeek:
    api_key = settings.DEEPSEEK_API_KEY
    if api_key is None or not api_key.get_secret_value().strip():
        raise BusinessException(code=503, message="AI 服务尚未配置，请联系管理员")

    return ChatDeepSeek(
        model=settings.DEEPSEEK_MODEL,
        api_key=api_key,
        base_url=settings.DEEPSEEK_BASE_URL,
        timeout=settings.DEEPSEEK_TIMEOUT_SECONDS,
        max_retries=2,
        temperature=0.2,
    )


def build_model_messages(data: ChatRequest) -> list[BaseMessage]:
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for message in data.messages:
        message_type = HumanMessage if message.role == "user" else AIMessage
        messages.append(message_type(content=message.content))
    return messages


def chat(data: ChatRequest, model: BaseChatModel | None = None) -> ChatResponse:
    try:
        chat_model = model or get_chat_model()
        response = chat_model.invoke(build_model_messages(data))
    except BusinessException:
        raise
    except Exception as exc:
        raise BusinessException(
            code=503, message="AI 服务暂时不可用，请稍后重试"
        ) from exc

    content = str(response.text).strip()
    if not content:
        raise BusinessException(code=502, message="AI 服务没有返回有效内容")

    return ChatResponse(content=content)
