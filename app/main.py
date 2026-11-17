"""The FastAPI application: every endpoint under api.prefix (app.properties), default /app.

Run from mangla_backend/:  python -m app   (or: uvicorn app.main:app --reload)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException  # also catches Starlette's own 404/405

from app.config import get_settings
from app.errors import InvalidInputError, NotFoundError
from app.logging_setup import configure_logging
from app.request_id import RequestIdMiddleware, UnhandledErrorMiddleware, get_request_id
from app.routers import account, cart, home, media, orders, reviews
from app.steps import audit_writer
from packages.storage import StorageError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s %s", app.title, app.version)
    yield
    # Let waiting audit rows reach Supabase before the process exits, but not forever.
    timeout = get_settings().audit_flush_timeout_seconds
    if not await asyncio.to_thread(audit_writer.flush, timeout):
        logger.warning("Stopping with %d audit rows not written after %.0f s",
                       audit_writer.pending(), timeout)
    logger.info("Stopped %s", app.title)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

    # add_middleware wraps: the last added runs first. Order per request:
    # RequestIdMiddleware (ID before anything else) -> CORSMiddleware -> UnhandledErrorMiddleware
    # (its 500 passes back through CORS, so browsers can read it) -> the routes.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[settings.request_id_header],
    )
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        logger.warning("HTTP %d: %s", exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": get_request_id()},
            headers=exc.headers,
        )

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404,
                            content={"detail": exc.detail, "request_id": get_request_id()})

    @app.exception_handler(InvalidInputError)
    async def invalid_input(request: Request, exc: InvalidInputError) -> JSONResponse:
        return JSONResponse(status_code=422,
                            content={"detail": exc.detail, "request_id": get_request_id()})

    @app.exception_handler(StorageError)
    async def storage_error(request: Request, exc: StorageError) -> JSONResponse:
        logger.error("Storage error: %s", exc)
        return JSONResponse(status_code=502,
                            content={"detail": "File storage is unavailable, try again",
                                     "request_id": get_request_id()})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        # %r: the summary is quoted and escaped, so request text cannot add lines to the log
        logger.warning("Invalid request body: %r",
                       "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors))
        # A body that was not JSON shows up as raw bytes in 'input'; decode leniently so a
        # non-UTF-8 body still gets its 422 instead of failing in the encoder.
        content = jsonable_encoder(
            {"detail": errors, "request_id": get_request_id()},
            custom_encoder={bytes: lambda b: b.decode("utf-8", "replace")},
        )
        return JSONResponse(status_code=422, content=content)

    for module in (orders, home, cart, account, reviews, media):
        app.include_router(module.router, prefix=settings.api_prefix)
    logger.info("Routes mounted under %s", settings.api_prefix or "/")
    return app


app = create_app()
