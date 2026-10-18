"""Authenticated, bounded read tools for plain chat; no business write capability."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select

from app.agent.policy import BudgetExceeded
from app.models.users import User
from app.schemas.reservation import TIME_PATTERN
from app.services.space_discovery import SpaceAvailabilityConditions, discover_spaces, search_space_catalogue
from app.services.time_context import BEIJING, now_beijing, resolve_date_expression


class ResolveDate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expression: str = Field(min_length=1, max_length=80)


class SearchCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    keyword: str = Field(default="", max_length=100)
    page: int = Field(default=1, ge=1, le=10000, strict=True)


class CheckAvailability(SearchCatalogue):
    date_expression: str = Field(min_length=1, max_length=80)
    start: str = Field(pattern=TIME_PATTERN)
    end: str = Field(pattern=TIME_PATTERN)
    people: int | None = Field(default=None, ge=1, le=1000, strict=True)

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("结束时间需要晚于开始时间，同次查询不能跨天")
        return self


SCHEMAS = {"resolve_date_expression": ResolveDate, "search_space_catalogue": SearchCatalogue,
    "check_space_availability": CheckAvailability}
DESCRIPTIONS = {
    "resolve_date_expression": "按服务端北京时间解析日期。expression照抄用户日期措辞，如今天、下周六、周六或2026-10-24；不能自选参考时间或将含糊日期改写成确定日期。周六/周末返回待澄清候选。",
    "search_space_catalogue": "只读查询真实登记空间的名称、房间号、馆区、类型、容量和设施，每页6条。keyword只放简短名称/类型/设施，无条件留空。无需日期或预约用途。结果不证明某日开放或空闲。",
    "check_space_availability": "只读检查明确日期及起止时段的空间预约条件。date_expression保留用户的日期措辞，含糊时会返回待澄清。start/end必须来自用户明确时间，不得猜测下午/全天的起止。people仅在用户明确人数时填写；无需用途。仅检查维护、容量、已批准预约冲突和提前两小时规则；尚无正式开放日历。不能预约或承诺获批。",
}


def tool_definitions():
    return [{"name": name, "description": DESCRIPTIONS[name], "parameters": schema.model_json_schema()}
        for name, schema in SCHEMAS.items()]


def error(code, message):
    return {"ok": False, "error_code": code, "message": message, "data": None}


def execute_chat_tool(db, user_id, name, arguments, budget, *, now=None):
    try:
        budget.consume("tool")
        if name not in SCHEMAS:
            return error("tool_not_allowed", "普通聊天只支持日期解析和空间查询，不能办理业务。")
        args = SCHEMAS[name].model_validate(arguments)
        if db is None or user_id is None:
            return error("unauthorized", "请登录后查询实时空间。")
        with db.no_autoflush:
            active = db.scalar(select(User.id).where(User.id == user_id, User.status == 1))
            if active is None:
                return error("unauthorized", "账号不可用，请重新登录。")
            instant = now if now is not None else now_beijing()
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError("Timezone required")
            instant = instant.astimezone(BEIJING)
            if name == "resolve_date_expression":
                data = resolve_date_expression(args.expression, instant)
            elif name == "search_space_catalogue":
                data = search_space_catalogue(db, args.keyword, args.page, checked_at=instant)
            else:
                resolved = resolve_date_expression(args.date_expression, instant)
                if resolved["status"] != "resolved":
                    return {"ok": True, "error_code": None, "data": resolved}
                if resolved["is_past"]:
                    return error("past_date", f"{resolved['date']}已经过去，请明确要查询的未来日期。")
                conditions = SpaceAvailabilityConditions(date=resolved["date"], start=args.start,
                    end=args.end, people=args.people)
                data = discover_spaces(db, conditions, args.keyword, args.page, checked_at=instant)
                data.update(opening_calendar="not_configured", message=(
                    "仅为已配置预约规则的检查结果，不证明实际开馆或保证获批。未配置正式开放日历；"
                    "人数未填写时未检查人数容量。待审核申请不锁定时段，提交时会再次校验。"))
        budget.remaining()
        return {"ok": True, "error_code": None, "data": data}
    except ValidationError:
        return error("invalid_arguments", "查询条件不完整或不合法，请明确日期及起止时间，人数如填写须为正整数。")
    except BudgetExceeded:
        return error("budget_exceeded", "本次查询已达到执行上限，请缩小范围后重试。")
    except Exception:
        if db is not None:
            db.rollback()
        return error("unavailable", "空间查询暂时不可用，请稍后重试。")
