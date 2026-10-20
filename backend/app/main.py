from fastapi import FastAPI

from app.contracts import install_contracts
from app.errors import install_errors
from app.schemas import ErrorOut


def create_app():
    app = FastAPI(
        title="GOAT business analytics API",
        version="0.1.0",
        description="A-01: models and HTTP contract. Business operations return 501 until implemented.",
        responses={code: {"model": ErrorOut} for code in [401, 403, 404, 409, 413, 422, 503]},
    )
    import uuid

    from fastapi import Request

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    install_errors(app)
    install_contracts(app)

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok", "mode": "contract-only"}

    return app


app = create_app()
