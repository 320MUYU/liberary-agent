"""Server-owned Beijing clock and deterministic Chinese calendar expressions."""

from datetime import date, datetime, timedelta, timezone
import re


# Modern Beijing time is UTC+08:00. A fixed offset also works on Windows without
# an additional IANA tzdata installation; the public zone name stays explicit.
BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")
WEEKDAYS = "一二三四五六日"


def now_beijing():
    return datetime.now(BEIJING)


def time_context(now=None):
    instant = now if now is not None else now_beijing()
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Reference time must include a timezone")
    instant = instant.astimezone(BEIJING)
    return {"now": instant.isoformat(timespec="seconds"), "date": instant.date().isoformat(),
        "weekday": "周" + WEEKDAYS[instant.weekday()], "timezone": "Asia/Shanghai",
        "week_starts_on": "Monday"}


def resolve_date_expression(expression, now=None):
    context = time_context(now)
    today = date.fromisoformat(context["date"])
    monday = today - timedelta(days=today.weekday())
    text = expression.strip()
    result = {"status": "needs_clarification", "date": None, "candidates": [],
        "reference": context, "message": "请明确具体年月日；含糊日期不能用于空闲查询。"}
    resolved = None
    offsets = {"前天": -2, "昨天": -1, "今天": 0, "明天": 1, "后天": 2}
    if text in offsets:
        resolved = today + timedelta(days=offsets[text])
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            resolved = date.fromisoformat(text)
        except ValueError:
            pass
    elif match := re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text):
        try:
            resolved = date(*(int(part) for part in match.groups()))
        except ValueError:
            pass
    elif match := re.fullmatch(r"(本|这|下下|下|上)?(?:周|星期|礼拜)([一二三四五六日天])", text):
        prefix, weekday = match.groups()
        target = monday + timedelta(days=WEEKDAYS.index("日" if weekday == "天" else weekday))
        if prefix:
            resolved = target + timedelta(weeks={"本": 0, "这": 0, "下": 1, "下下": 2, "上": -1}[prefix])
        else:
            result["candidates"] = [
                {"date": day.isoformat(), "weekday": "周" + WEEKDAYS[day.weekday()], "label": label}
                for day, label in [(target, "本周"), (target + timedelta(weeks=1), "下周")]]
            result["message"] = "请确认指的是本周还是下周，并在回复中写出具体日期。"
    elif text in {"周末", "本周末", "这周末", "下周末"}:
        saturday = monday + timedelta(days=5, weeks=1 if text == "下周末" else 0)
        result["candidates"] = [{"date": (saturday + timedelta(days=i)).isoformat(),
            "weekday": "周" + WEEKDAYS[5 + i]} for i in range(2)]
        result["message"] = "周末包含周六和周日，请明确日期。"
    if resolved is not None:
        result.update(status="resolved", date=resolved.isoformat(), is_past=resolved < today,
            weekday="周" + WEEKDAYS[resolved.weekday()], message="已解析为北京时间日期。")
    return result
