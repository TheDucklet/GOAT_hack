import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import routers
from app.api.error_handlers import install_errors
from app.config import get_settings
from app.contracts import install_contracts
from app.db import get_engine
from app.schemas import ErrorOut
from app.security import guard_contract


def create_app():
    app = FastAPI(
        title="GOAT business analytics API",
        version="0.1.0",
        responses={code: {"model": ErrorOut} for code in [401, 403, 404, 409, 413, 422, 503]},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path not in {"/health", "/docs", "/openapi.json", "/redoc"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    install_errors(app)
    for router in routers:
        app.include_router(router)
    install_contracts(app, access_dependency=guard_contract)

    @app.get("/health", tags=["system"])
    def health():
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"status": "ok"}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})

    return app


app = create_app()
