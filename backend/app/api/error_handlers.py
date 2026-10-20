from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from app.errors import AppError


def _error_response(request, status, code, message, *, field_errors=None, headers=None):
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", "unknown"),
            "field_errors": field_errors or [],
        },
        headers=headers,
    )


def install_errors(app: FastAPI):

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        return _error_response(
            request, 500, "internal_error", "Внутренняя ошибка сервера", headers={"X-Request-ID": request_id}
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return _error_response(
            request,
            exc.status_code,
            "not_found" if exc.status_code == 404 else "http_error",
            "Ресурс не найден" if exc.status_code == 404 else "Запрос отклонён",
            headers=exc.headers,
        )

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return _error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error_response(
            request,
            422,
            "validation_error",
            "Проверьте поля запроса",
            field_errors=[
                {"loc": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()
            ],
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError):
        return _error_response(request, 409, "conflict", "Запись уже существует или конфликтует с данными")
