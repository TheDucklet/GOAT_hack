from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def install_errors(app: FastAPI):
    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Внутренняя ошибка сервера",
                "request_id": request_id,
                "field_errors": [],
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": "not_found" if exc.status_code == 404 else "http_error",
                "message": "Ресурс не найден" if exc.status_code == 404 else "Запрос отклонён",
                "request_id": request.state.request_id,
                "field_errors": [],
            },
            headers=exc.headers,
        )

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
                "field_errors": [],
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Проверьте поля запроса",
                "request_id": request.state.request_id,
                "field_errors": [
                    {"loc": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()
                ],
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError):
        return JSONResponse(
            status_code=409,
            content={
                "code": "conflict",
                "message": "Запись уже существует или конфликтует с данными",
                "request_id": request.state.request_id,
                "field_errors": [],
            },
        )
