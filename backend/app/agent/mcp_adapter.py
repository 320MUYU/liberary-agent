"""Private first-party MCP transport; credentials never enter model context."""

import asyncio
import hashlib
import hmac
import time
from urllib.parse import urlsplit

import httpx
import jwt
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.common.exceptions import BusinessException
from app.config import settings


AUDIENCE = "library-mcp"
ISSUER = "library-agent-runtime"


def signing_key():
    return hmac.new(settings.JWT_SECRET_KEY.encode(), b"library-mcp-v1", hashlib.sha256).digest()


def issue_token(user_id, action_id=None, confirmed=None):
    claims = {"sub": str(user_id), "aud": AUDIENCE, "iss": ISSUER,
              "iat": int(time.time()), "exp": int(time.time()) + 90, "scope": "catalogue:read"}
    if action_id is not None:
        if type(confirmed) is not bool:
            raise ValueError("Invalid confirmation")
        claims.update(scope="borrow:decision", action_id=action_id, confirmed=confirmed)
    return jwt.encode(claims, signing_key(), algorithm="HS256")


def verify_token(token):
    return jwt.decode(token, signing_key(), algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
                      options={"require": ["sub", "aud", "iss", "iat", "exp", "scope"]})


async def _call(user_id, name, arguments, timeout, action_id=None, confirmed=None):
    url = settings.AGENT_MCP_URL
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"})):
        raise ValueError("Invalid MCP endpoint")
    token = issue_token(user_id, action_id, confirmed)
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False,
                headers={"Authorization": "Bearer " + token}) as client:
            async with streamable_http_client(url, http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                    if result.isError or not isinstance(result.structuredContent, dict):
                        raise ValueError("Invalid MCP result")
                    return result.structuredContent


def read_tool(user_id, name, arguments, budget):
    from app.agent.tools import SCHEMAS, error
    from app.agent.policy import BudgetExceeded
    from pydantic import ValidationError
    try:
        budget.consume("tool")
        if name not in SCHEMAS:
            return error("tool_not_allowed", "不支持的工具")
        arguments = SCHEMAS[name].model_validate(arguments).model_dump()
        return asyncio.run(_call(user_id, name, arguments, min(15, budget.remaining())))
    except ValidationError:
        return error("invalid_arguments", "工具参数不合法")
    except BudgetExceeded:
        return error("budget_exceeded", "查询次数已达上限")
    except Exception:
        return error("unavailable", "图书工具暂时不可用，请稍后重试", True)


def submit_decision(user_id, action_id, confirmed):
    try:
        result = asyncio.run(_call(user_id, "submit_borrow_decision",
            {"action_id": action_id, "confirmed": confirmed}, 15, action_id, confirmed))
    except Exception:
        raise BusinessException("申请结果暂时无法确认，请刷新任务并重试查询回执。", 503) from None
    if not result.get("ok"):
        raise BusinessException(result.get("message", "操作未完成"), int(result.get("error_code", 409)))
    return result["data"]
