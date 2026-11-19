"""FastAPI 入口：中间件、异常、路由、静态页。"""
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.v1 import chat as chat_api
from app.api.v1 import health as health_api
from app.api.v1 import memories as memories_api
from app.core import config, exceptions, logging, metrics, scheduler
from app.core.logging import setup_logging, trace_id_var

setup_logging(config.settings.log_level)
log = logging.get_logger("memkeep.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        scheduler.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("scheduler_start_failed", extra={"extra": str(exc)})
    yield
    scheduler.shutdown()


app = FastAPI(
    title=config.settings.app_name,
    version=config.settings.version,
    description="Agent 长期记忆系统：抽取 → 冲突消解 → 检索 → 作答",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

limiter = metrics.RateLimiter(config.settings.rate_limit_per_min)
SKIP_LIMIT = {"/health", "/metrics", "/docs", "/openapi.json"}


@app.middleware("http")
async def observability(request: Request, call_next):
    tid = uuid.uuid4().hex[:12]
    token = trace_id_var.set(tid)
    started = time.perf_counter()

    if request.url.path not in SKIP_LIMIT:
        client = request.client.host if request.client else "-"
        if not limiter.allow(client):
            trace_id_var.reset(token)
            return JSONResponse(
                status_code=429,
                content=exceptions.RateLimitedError().to_dict(tid),
            )

    try:
        response = await call_next(request)
    except exceptions.AppError as exc:
        metrics.inc("errors")
        response = JSONResponse(status_code=exc.status, content=exc.to_dict(tid))
    except Exception as exc:  # noqa: BLE001
        metrics.inc("errors")
        log.exception("unhandled", extra={"path": request.url.path, "extra": str(exc)})
        response = JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "服务内部错误",
                    "trace_id": tid,
                }
            },
        )

    latency = int((time.perf_counter() - started) * 1000)
    metrics.inc("requests")
    metrics.observe_latency(latency)
    response.headers["X-Trace-Id"] = tid
    log.info(
        "request",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "latency_ms": latency,
        },
    )
    trace_id_var.reset(token)
    return response


@app.exception_handler(exceptions.AppError)
async def handle_app_error(request: Request, exc: exceptions.AppError):
    return JSONResponse(status_code=exc.status, content=exc.to_dict(trace_id_var.get()))


app.include_router(health_api.router)
app.include_router(chat_api.router)
app.include_router(memories_api.router)

# ---- 兼容旧前端：把 /api/chat 与 /api/memories 转到新服务，避免重构期间界面坏掉 ----


@app.post("/api/chat", include_in_schema=False)
def legacy_chat(payload: dict):
    from app.services.memory_service import MemoryService

    msg = (payload or {}).get("message", "")
    res, written = MemoryService().chat(msg)
    return {"reply": res.get("answer", ""), "used": res.get("used", []), "written": written}


@app.get("/api/memories", include_in_schema=False)
def legacy_memories(limit: int = 200):
    from app.repositories.sqlite_repo import SqliteRepository
    from app.core import config as cfg

    conn = SqliteRepository(cfg.settings.sqlite_path).connect()
    try:
        items = SqliteRepository(cfg.settings.sqlite_path).list_active(conn, limit)
        return {"items": items, "stats": SqliteRepository(cfg.settings.sqlite_path).stats(conn)}
    finally:
        conn.close()


@app.delete("/api/memories/{mem_id}", include_in_schema=False)
def legacy_delete(mem_id: int):
    from app.services.memory_service import MemoryService

    return MemoryService().delete(mem_id)


WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
DIST_DIR = os.path.join(WEB_DIR, "dist")
LEGACY_DIR = os.path.join(WEB_DIR, "templates")


@app.get("/", include_in_schema=False)
def index():
    dist_index = os.path.join(DIST_DIR, "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index)
    legacy = os.path.join(LEGACY_DIR, "index.html")
    if os.path.exists(legacy):
        return FileResponse(legacy)
    return JSONResponse({"service": config.settings.app_name, "docs": "/docs"})


if os.path.isdir(os.path.join(DIST_DIR, "assets")):
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")
