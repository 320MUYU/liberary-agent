from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.common.response import Response


class BusinessException(Exception):
    """自定义的业务异常"""

    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


async def business_exception_handler(request: Request, exc: BusinessException):
    """自定义业务异常处理器"""
    return JSONResponse(
        status_code=200,
        content=Response.error(code=exc.code, message=exc.message).model_dump(),
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理器"""
    return JSONResponse(
        status_code=exc.status_code,
        content=Response.error(code=exc.status_code, message=exc.detail).model_dump(),
    )


# pydantic 内置的校验消息是英文，这里把最常撞到的几种翻成中文
VALIDATION_TYPE_MESSAGES = {
    "missing": "为必填项",
    "string_too_short": "长度不能少于 {min_length} 位",
    "string_too_long": "长度不能超过 {max_length} 位",
}


def format_validation_error(exc: RequestValidationError) -> str:
    """把校验错误压成一句能直接给用户看的中文提示

    exc.errors() 是一张列表，每项大致长这样：
        {"type": "string_too_short", "loc": ("body", "username"), "msg": "...", "ctx": {...}}
    一次可能有多个字段出错，这里只取第一条——用户一次修一个就够了。
    """
    errors = exc.errors()
    if not errors:
        return "请求参数校验错误"

    first_error = errors[0]

    # loc 是"错误位置"的路径，形如 ("body", "username")
    # 前面几段是 body/query/path 这类来源标记，最后一段才是真正的字段名
    location = [
        str(item)
        for item in first_error.get("loc", [])
        if item not in ("body", "query", "path")
    ]
    field_name = location[-1] if location else "参数"

    message = first_error.get("msg", "")

    # 情况一：我们自己 raise ValueError("中文提示")，pydantic 会自动加上 "Value error, " 前缀。
    # 这种消息已经是写给用户看的，去掉前缀直接用。
    if message.startswith("Value error, "):
        return message.removeprefix("Value error, ")

    # 情况二：pydantic 内置的英文消息，按类型换成中文模板
    error_type = first_error.get("type", "")
    template = VALIDATION_TYPE_MESSAGES.get(error_type)
    if template:
        return f"{field_name} " + template.format(**first_error.get("ctx", {}))

    # 情况三：没覆盖到的类型，带上字段名兜底，至少让用户知道是哪个字段
    return f"{field_name}: {message}"


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数异常处理器"""
    return JSONResponse(
        status_code=422,
        content=Response.error(
            code=422, message=format_validation_error(exc)
        ).model_dump(),
    )


async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    return JSONResponse(
        status_code=500,
        content=Response.error(code=500, message="服务器内部错误").model_dump(),
    )
