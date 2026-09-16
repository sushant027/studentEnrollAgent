"""FastAPI application: middleware, routes, startup.

Run single-worker — session memory is an in-process MemorySaver:
    uvicorn app.main:app --reload --workers 1
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.constants.constants import Events
from app.controller import auth_controller, chat_controller
from app.repository.student_repository import init_db
from app.utilities.logger import (
    clear_context,
    configure_logging,
    get_logger,
    new_request_id,
    set_context,
)

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)
templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.event("STARTUP", "starting enrollment assistant",
              app_env=settings.app_env, model=settings.openai_model,
              max_chat_history=settings.max_chat_history,
              openai_key_present=settings.has_openai_key)
    init_db()
    if not settings.has_openai_key:
        log.warn(Events.ERROR, "OPENAI_API_KEY is not set — chat turns will fail",
                 hint="copy .env.example to .env and fill in your key")
    yield
    log.event("SHUTDOWN", "stopping enrollment assistant")


app = FastAPI(
    title="Student Enrollment Assistant",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    """Assign a request_id and bind it for every log line produced by this request."""
    request_id = new_request_id()
    clear_context()
    set_context(request_id=request_id)
    log.debug(Events.REQUEST_RECEIVED, "http request",
              method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        log.error(Events.ERROR, "unhandled error", exc_info=True,
                  method=request.method, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    log.debug("HTTP_RESPONSE", "http response",
              status_code=response.status_code, path=request.url.path)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    log.warn(Events.ERROR, "invalid request body", path=request.url.path,
             error_count=len(exc.errors()))
    return JSONResponse(status_code=422, content={"detail": "Invalid request"})


app.include_router(auth_controller.router)
app.include_router(chat_controller.router)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")
