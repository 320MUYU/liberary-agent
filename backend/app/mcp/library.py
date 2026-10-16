from contextvars import ContextVar
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field, StrictBool
from starlette.responses import JSONResponse

from app.agent.actions import decide_borrow
from app.agent.mcp_adapter import verify_token
from app.agent.policy import RunBudget
from app.agent.tools import execute_read_tool, error
from app.common.exceptions import BusinessException
from app.database import SessionLocal


identity = ContextVar("library_mcp_identity", default=None)


class Authenticate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            value = dict(scope["headers"]).get(b"authorization", b"").decode()
            if not value.startswith("Bearer "):
                raise ValueError()
            claims = verify_token(value[7:])
            if not str(claims["sub"]).isdigit():
                raise ValueError()
        except Exception:
            return await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
        token = identity.set(claims)
        try:
            await self.app(scope, receive, send)
        finally:
            identity.reset(token)


def create_server(session_factory=SessionLocal):
    server = FastMCP("library", host="127.0.0.1", port=8002, stateless_http=True, json_response=True)

    def read(name, arguments):
        claims = identity.get()
        if not claims or claims.get("scope") != "catalogue:read":
            return error("403", "工具权限不足")
        with session_factory() as db:
            return execute_read_tool(db, int(claims["sub"]), name, arguments, RunBudget())

    @server.tool()
    async def search_books(keyword: str, page: Annotated[int, Field(strict=True, ge=1, le=100)] = 1) -> dict[str, Any]:
        """查询上架书目，不提交借阅申请。"""
        return read("search_books", {"keyword": keyword, "page": page})

    @server.tool()
    async def get_book(book_id: Annotated[int, Field(strict=True, gt=0)]) -> dict[str, Any]:
        """查询上架书目详情和实际库存。"""
        return read("get_book", {"book_id": book_id})

    @server.tool()
    async def submit_borrow_decision(action_id: str, confirmed: StrictBool) -> dict[str, Any]:
        """执行服务端已授权的具体确认；普通查询凭证不能调用。"""
        claims = identity.get()
        if (not claims or claims.get("scope") != "borrow:decision"
                or claims.get("action_id") != action_id or claims.get("confirmed") is not confirmed):
            return error("403", "缺少本次操作的确认授权")
        try:
            with session_factory() as db:
                receipt = decide_borrow(db, int(claims["sub"]), action_id, confirmed)
                return {"ok": True, "data": receipt}
        except BusinessException as exc:
            return error(str(exc.code), exc.message)
        except Exception:
            return error("503", "操作结果暂时无法确认，请查询任务回执", True)

    return server, Authenticate(server.streamable_http_app())


server, app = create_server()
