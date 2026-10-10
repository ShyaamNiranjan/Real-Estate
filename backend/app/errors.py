"""Every error leaves the API as {"error": {"code": ..., "message": ...}}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


class ErrorBody(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def _body(code: str, message: str, fields: dict[str, str] | None = None) -> dict:
    return ErrorResponse(error=ErrorBody(code=code, message=message, fields=fields)).model_dump(exclude_none=True)


def friendly(error: dict) -> str:
    """Plain-English text for the validation failures people actually hit; Pydantic's wording otherwise."""
    kind, ctx = error["type"], error.get("ctx") or {}
    if kind == "missing":
        return "This is required."
    if kind == "string_too_short":
        n = ctx.get("min_length", 1)
        return "This is required." if n == 1 else f"Use at least {n} characters."
    if kind == "string_too_long":
        return f"Keep this to {ctx.get('max_length')} characters or fewer."
    if kind == "value_error" and "email" in error["msg"].lower():
        return "Enter a valid email address."
    if kind == "value_error":
        return error["msg"].removeprefix("Value error, ")
    if kind == "string_pattern_mismatch":
        return "This isn't in the right format."
    if kind == "literal_error" and ctx.get("expected") == "True":
        return "Please tick this box."
    if kind in ("int_parsing", "float_parsing", "int_type", "float_type"):
        return "Enter a number."
    if kind in ("greater_than", "greater_than_equal"):
        return f"Must be at least {ctx.get('gt', ctx.get('ge'))}."
    if kind in ("less_than", "less_than_equal"):
        return f"Must be at most {ctx.get('lt', ctx.get('le'))}."
    if kind in ("url_parsing", "url_scheme", "url_type"):
        return "Enter a full link starting with https://"
    if kind == "too_long":
        return f"Choose up to {ctx.get('max_length')}."
    return error["msg"]


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for e in exc.errors():
            # Union members add tags like "literal['']" to loc; the first branch's message is the useful one.
            key = ".".join(str(p) for p in e["loc"][1:] if not (isinstance(p, str) and "[" in p)) or "body"
            fields.setdefault(key, friendly(e))
        return JSONResponse(_body("validation_error", "Some fields need attention.", fields), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)
