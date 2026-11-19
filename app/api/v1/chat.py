"""问答与写入接口。"""
import time

from fastapi import APIRouter, Depends

from app.core import logging, metrics
from app.core.security import require_api_key
from app.schemas.memory import (
    ChatRequest,
    ChatResponse,
    IngestRequest,
    IngestResponse,
    UsedMemory,
    WrittenMemory,
)
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api/v1", tags=["chat"], dependencies=[Depends(require_api_key)])
log = logging.get_logger("memkeep.api.chat")


def _svc() -> MemoryService:
    return MemoryService()


def _norm_written(items: list[dict]) -> list[WrittenMemory]:
    out = []
    for r in items or []:
        out.append(
            WrittenMemory(
                action=r.get("action", "new"),
                attribute=r.get("attr") or r.get("attribute"),
                value=r.get("value"),
            )
        )
    return out


@router.post("/chat", response_model=ChatResponse, summary="提问，返回基于记忆的答案")
def chat(req: ChatRequest):
    started = time.perf_counter()
    svc = _svc()
    try:
        res, written = svc.chat(req.message)
    except Exception:
        metrics.inc("llm_failures")
        raise
    latency = int((time.perf_counter() - started) * 1000)
    log.info(
        "chat",
        extra={"latency_ms": latency, "stage": "chat", "extra": f"used={len(res.get('used', []))}"},
    )
    return ChatResponse(
        answer=res.get("answer", ""),
        intent=res.get("intent", "semantic"),
        refused=bool(res.get("refused", False)),
        used=[UsedMemory(**u) for u in res.get("used", [])],
        written=_norm_written(written),
        latency_ms=latency,
        trace_id=logging.trace_id_var.get(),
    )


@router.post("/ingest", response_model=IngestResponse, summary="显式写入一段对话")
def ingest(req: IngestRequest):
    svc = _svc()
    written = svc.ingest(req.text, session_id=req.session_id, date=req.date)
    conflicts = sum(1 for w in written if w.get("action") == "update")
    return IngestResponse(written=_norm_written(written), conflicts=conflicts)
