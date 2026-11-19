"""记忆管理接口。"""
from fastapi import APIRouter, Depends, Query

from app.core.security import require_api_key
from app.schemas.memory import MemoryDeleteResponse, MemoryItem, MemoryListResponse
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api/v1", tags=["memories"], dependencies=[Depends(require_api_key)])


@router.get("/memories", response_model=MemoryListResponse, summary="列出活跃记忆")
def list_memories(limit: int = Query(default=200, ge=1, le=1000)):
    svc = MemoryService()
    items, stats = svc.list(limit)
    return MemoryListResponse(
        total=stats["total"],
        by_category=stats["by_category"],
        items=[
            MemoryItem(
                id=m["id"],
                subject=m["subject"],
                attribute=m["attribute"],
                value=m["value"],
                category=m["category"],
                confidence=float(m.get("confidence") or 0.8),
                score=float(m.get("score") or 0),
                status=m.get("status") or "active",
                created_at=m.get("created_at"),
            )
            for m in items
        ],
    )


@router.delete("/memories/{mem_id}", response_model=MemoryDeleteResponse, summary="删除一条记忆")
def delete_memory(mem_id: int):
    return MemoryDeleteResponse(**MemoryService().delete(mem_id))


@router.get("/conflicts", summary="查看冲突处理记录")
def list_conflicts(limit: int = Query(default=30, ge=1, le=200)):
    return {"items": MemoryService().conflicts(limit)}
