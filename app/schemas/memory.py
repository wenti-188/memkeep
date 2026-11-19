"""Pydantic 请求/响应模型。接口契约写在这里，改字段会立刻反映到 /docs。"""
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["identity", "preference", "goal", "relation", "event"]


class MemoryItem(BaseModel):
    id: int
    subject: str
    attribute: str
    value: str
    category: Category
    confidence: float
    score: float = Field(description="保留分，用于面板展示")
    status: Literal["active", "superseded", "deleted"]
    created_at: str | None = None


class MemoryListResponse(BaseModel):
    total: int
    by_category: dict[str, int]
    items: list[MemoryItem]


class MemoryDeleteResponse(BaseModel):
    id: int
    status: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="用户这一轮说的话")
    session_id: str | None = Field(default=None, description="会话标识，用于把多轮归到同一段")


class UsedMemory(BaseModel):
    id: int
    attribute: str
    value: str
    category: str
    score: float


class WrittenMemory(BaseModel):
    action: Literal["new", "update", "coexist", "repeat"]
    attribute: str | None = None
    value: str | None = None


class ChatResponse(BaseModel):
    answer: str
    intent: str
    refused: bool
    used: list[UsedMemory]
    written: list[WrittenMemory]
    latency_ms: int
    trace_id: str


class IngestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="一段对话原文，直接抽事实写入")
    session_id: str | None = None
    date: str | None = Field(default=None, description="对话发生日期，YYYY-MM-DD")


class IngestResponse(BaseModel):
    written: list[WrittenMemory]
    conflicts: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: str
    llm: str
    version: str


class MetricsResponse(BaseModel):
    requests_total: int
    errors_total: int
    latency_p50_ms: int
    latency_p95_ms: int
    llm_failures: int
