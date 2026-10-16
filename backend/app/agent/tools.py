"""One read-tool contract shared by local execution and the MCP adapter."""

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.agent.policy import BudgetExceeded
from app.common.exceptions import BusinessException
from app.models.users import User
from app.services import book_service, loan_service
from app.schemas.loan import LoanStatus
from app.services.book_discovery import discover_books, public_book


class SearchBooks(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["auto", "exact", "topic"] = "auto"
    keyword: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1, le=100, strict=True)


class GetBook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    book_id: int = Field(gt=0, strict=True)


class ListMyLoans(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    page: int = Field(default=1, ge=1, le=10000, strict=True)
    status: LoanStatus | None = None
    keyword: str = Field(default="", max_length=100)


class GetMyLoan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    loan_id: int = Field(gt=0, strict=True)


SCHEMAS = {"search_books": SearchBooks, "get_book": GetBook,
           "list_my_loans": ListMyLoans, "get_my_loan": GetMyLoan}
DESCRIPTIONS = {
    "search_books": "查询上架书目，每页6本。具体书名、作者、ISBN用exact；主题推荐用topic，融合分类、标签和已发布元数据知识库。auto优先精确。返回匹配依据、来源及实时馆藏，降级会标记。只读。",
    "get_book": "查询已上架书目的详细信息和当前可借册数。只读，不占库存。",
    "list_my_loans": "查询当前登录读者的实际借阅记录，每页6条。可按书名、作者、ISBN关键词和状态过滤；不要把查询我的借阅等请求用语放入关键词。borrowed为借阅中，return_pending为待确认归还，returned为已归还。只读。",
    "get_my_loan": "按借阅记录编号查询当前读者的一条记录。只读，不申请归还。",
}


def allowed_tools(task_type="borrow"):
    return {"search_books", "get_book"} if task_type == "borrow" else {"list_my_loans", "get_my_loan"}


def tool_definitions(task_type="borrow"):
    return [{"name": name, "description": DESCRIPTIONS[name], "parameters": schema.model_json_schema()}
            for name, schema in SCHEMAS.items() if name in allowed_tools(task_type)]


def public_loan(loan):
    return loan.model_dump(mode="json", exclude={"reader_id", "reader_name", "reader_username"})


def error(code, message, retryable=False):
    return {"ok": False, "error_code": code, "message": message, "retryable": retryable, "data": None}


def execute_read_tool(db, user_id, name, arguments, budget):
    try:
        budget.consume("tool")
        active = db.scalar(select(User.id).where(User.id == user_id, User.status == 1))
        if active is None:
            return error("unauthorized", "账号不可用，请重新登录")
        schema = SCHEMAS.get(name)
        if schema is None:
            return error("tool_not_allowed", "不支持的工具")
        args = schema.model_validate(arguments)
        if name == "search_books":
            data = discover_books(db, args.keyword, args.page, mode=args.mode,
                deadline=time.monotonic() + min(10, budget.remaining()))
        elif name == "get_book":
            data = {"books": [public_book(book_service.get_book_detail(db, args.book_id))]}
        else:
            user = db.get(User, user_id)
            if name == "list_my_loans":
                total, loans = loan_service.list_my_loans(db, user, args.page, 6, args.status, args.keyword)
                data = {"total": total, "page": args.page, "page_size": 6,
                        "status": args.status, "keyword": args.keyword, "loans": [public_loan(l) for l in loans]}
            else:
                data = {"total": 1, "page": 1, "page_size": 6, "status": None, "keyword": "",
                        "loans": [public_loan(loan_service.get_my_loan(db, user, args.loan_id))]}
        budget.remaining()
        return {"ok": True, "error_code": None, "data": data, "retryable": False}
    except ValidationError:
        return error("invalid_arguments", "工具参数不合法，请检查关键词或书目编号")
    except BudgetExceeded:
        return error("budget_exceeded", "本次查询已达到执行上限，请缩小范围后重试")
    except BusinessException as exc:
        return error(str(exc.code), exc.message)
    except Exception:
        db.rollback()
        return error("unavailable", "图书查询暂时不可用", True)
