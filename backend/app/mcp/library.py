from contextvars import ContextVar
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field, StrictBool
from starlette.responses import JSONResponse

from app.agent.actions import decide_borrow, decide_return
from app.agent.reservation_actions import decide_reservation
from app.agent.mcp_adapter import verify_token
from app.agent.policy import RunBudget
from app.agent.tools import execute_read_tool, error
from app.common.exceptions import BusinessException
from app.database import SessionLocal
from app.schemas.loan import LoanStatus
from app.services.space_discovery import SpaceConditions


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
        required = "spaces:read" if name in {"search_spaces", "get_space"} else (
            "loans:read" if name in {"list_my_loans", "get_my_loan"} else "catalogue:read")
        if not claims or claims.get("scope") != required:
            return error("403", "工具权限不足")
        with session_factory() as db:
            return execute_read_tool(db, int(claims["sub"]), name, arguments, RunBudget())

    @server.tool()
    async def search_books(keyword: str, page: Annotated[int, Field(strict=True, ge=1, le=100)] = 1,
                           mode: Literal["auto", "exact", "topic"] = "auto") -> dict[str, Any]:
        """按具体书名或主题查询上架书目、匹配依据和实时馆藏，不提交申请。"""
        return read("search_books", {"keyword": keyword, "page": page, "mode": mode})

    @server.tool()
    async def get_book(book_id: Annotated[int, Field(strict=True, gt=0)]) -> dict[str, Any]:
        """查询上架书目详情和实际库存。"""
        return read("get_book", {"book_id": book_id})

    @server.tool()
    async def list_my_loans(page: Annotated[int, Field(strict=True, ge=1, le=10000)] = 1,
                            status: LoanStatus | None = None, keyword: str = "") -> dict[str, Any]:
        """只读查询当前凭证所属读者的借阅记录，不接受指定读者参数。"""
        return read("list_my_loans", {"page": page, "status": status, "keyword": keyword})

    @server.tool()
    async def get_my_loan(loan_id: Annotated[int, Field(strict=True, gt=0)]) -> dict[str, Any]:
        """只读查询本人具体借阅记录。"""
        return read("get_my_loan", {"loan_id": loan_id})

    @server.tool()
    async def search_spaces(conditions: SpaceConditions, keyword: str = "",
                            page: Annotated[int, Field(strict=True, ge=1, le=10000)] = 1) -> dict[str, Any]:
        """只读查询空间和指定时段可用性，不返回他人的预约信息。"""
        return read("search_spaces", {"conditions": conditions.model_dump(mode="json"), "keyword": keyword, "page": page})

    @server.tool()
    async def get_space(conditions: SpaceConditions, space_id: Annotated[int, Field(strict=True, gt=0)]) -> dict[str, Any]:
        """只读查询空间详情和指定时段状态。"""
        return read("get_space", {"conditions": conditions.model_dump(mode="json"), "space_id": space_id})

    @server.tool()
    async def submit_reservation_decision(action_id: str, confirmed: StrictBool) -> dict[str, Any]:
        """执行已绑定到具体预约操作的人工确认。"""
        return submit("reservation", action_id, confirmed)

    @server.tool()
    async def submit_borrow_decision(action_id: str, confirmed: StrictBool) -> dict[str, Any]:
        """执行服务端已授权的具体确认；普通查询凭证不能调用。"""
        return submit("borrow", action_id, confirmed)

    @server.tool()
    async def submit_return_decision(action_id: str, confirmed: StrictBool) -> dict[str, Any]:
        """执行服务端绑定到归还操作的确认；读凭证和借阅确认凭证均不能调用。"""
        return submit("return", action_id, confirmed)

    def submit(action_type, action_id, confirmed):
        claims = identity.get()
        if (not claims or claims.get("scope") != action_type + ":decision"
                or claims.get("action_id") != action_id or claims.get("confirmed") is not confirmed):
            return error("403", "缺少本次操作的确认授权")
        try:
            with session_factory() as db:
                handler = {"borrow": decide_borrow, "return": decide_return, "reservation": decide_reservation}[action_type]
                receipt = handler(db, int(claims["sub"]), action_id, confirmed)
                return {"ok": True, "data": receipt}
        except BusinessException as exc:
            return error(str(exc.code), exc.message)
        except Exception:
            return error("503", "操作结果暂时无法确认，请查询任务回执", True)

    return server, Authenticate(server.streamable_http_app())


server, app = create_server()
