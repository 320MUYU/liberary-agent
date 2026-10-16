"""One read-tool contract shared by local execution and the MCP adapter."""

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.agent.policy import BudgetExceeded
from app.common.exceptions import BusinessException
from app.models.users import User
from app.services import book_service
from app.services.book_discovery import discover_books, public_book


class SearchBooks(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["auto", "exact", "topic"] = "auto"
    keyword: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1, le=100, strict=True)


class GetBook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    book_id: int = Field(gt=0, strict=True)


SCHEMAS = {"search_books": SearchBooks, "get_book": GetBook}
DESCRIPTIONS = {
    "search_books": "查询上架书目，每页6本。具体书名、作者、ISBN用exact；主题推荐用topic，融合分类、标签和已发布元数据知识库。auto优先精确。返回匹配依据、来源及实时馆藏，降级会标记。只读。",
    "get_book": "查询已上架书目的详细信息和当前可借册数。只读，不占库存。",
}


def tool_definitions():
    return [{"name": name, "description": DESCRIPTIONS[name], "parameters": schema.model_json_schema()}
            for name, schema in SCHEMAS.items()]


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
        else:
            data = {"books": [public_book(book_service.get_book_detail(db, args.book_id))]}
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
