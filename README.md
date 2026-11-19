# MemKeep

给 LLM Agent 用的长期记忆层：从对话里抽取事实、判冲突、按保留分遗忘、按问题检索。

不是"把聊天记录塞进向量库再 top-k"，而是把对话变成**结构化、可冲突消解、会过期**的记忆条目，再按问题类型走不同的检索策略。

---

## 一句话定位

大模型不记事。把历史全塞回去 → 贵、慢、自相矛盾。
MemKeep 做的是中间那一层：**决定这次该让模型看到哪些事实**。

```
用户 ←→ 大模型（只负责生成）
           ↑
        ┌──────────┐
        │  MemKeep  │  抽什么 / 存多久 / 取哪些 / 冲突听谁的
        └──────────┘
           ↑
   Postgres + pgvector（HNSW）
```

它不训练模型，只解决记忆的存取管理。任何走 OpenAI 兼容接口的模型都能挂上来，换模型只改 `core/llm.py` 一个文件。

---

## 它解决的问题

| 裸上下文 | RAG over 聊天记录 | MemKeep |
|---|---|---|
| 越长越贵，超过窗口就丢 | 召回一堆重复、过期片段 | 条目级去重，同属性只留最新或并存 |
| 说过的话前后矛盾，模型自己打架 | 无法判断哪条该信 | 冲突判定 → supersede / coexist，带时间 |
| 没有遗忘，三年前一句玩笑还在 | 旧条目 forever 占召回位 | 保留分 `base × 频率 × e^(-λ·天数)` + 定时归档 |
| 未知问题照样编 | 未知问题照样编 | 检索不到就不答（拒答率可测） |

---
## 架构

```
写入侧
对话 ──► 抽取(LLM 双采样并集) ──► 同批合并 ──► 冲突判定 ──► 事务写入
                                                    │
                                      update(新值覆盖旧值) / coexist(不同侧面)

读取侧
问题 ──► 意图路由(preference/time/fact/semantic)
      ──► 三路召回：向量(HNSW) + 关键词(中英 n-gram) + 保留分
      ──► RRF 融合(1/(60+rank)) ──► 类别加权 ──► token 预算截断 ──► 作答
```

六层后端（与同类项目保持同一套分层习惯，便于横向对比）：

| 层 | 目录 | 职责 |
|---|---|---|
| 接口 | `app/api/v1/` | 路由、参数校验、错误码 |
| 服务 | `app/services/` | 编排：检索→作答→写入→镜像 |
| 领域 | `core/` | 抽取、冲突、检索、保留分（纯逻辑，不碰 HTTP） |
| 仓储 | `app/repositories/` | SQLite / Postgres 双实现 + 连接池 |
| 基础设施 | `app/core/` | 配置、日志、异常、限流、指标、调度 |
| 前端 | `frontend/` `web/dist/` | Vue3 + Vite，构建产物由 FastAPI 托管 |

---

## 技术栈

| 类别 | 选型 | 解决什么问题 |
|---|---|---|
| 服务框架 | FastAPI + Pydantic + Uvicorn | 校验、异步、自动 OpenAPI 文档 |
| 数据库 | Postgres 16 + pgvector | 事务、并发、向量原生类型 |
| 向量索引 | HNSW（`vector_cosine_ops`, m=16, ef=64） | 万级数据近邻检索从全表扫降到毫秒 |
| 连接管理 | psycopg2 ThreadedConnectionPool（阻塞取连接） | 并发下不再每次新建连接 |
| 调度 | APScheduler | 过期记忆定时归档（真执行，不是写在注释里） |
| 可靠性 | 超时 + 指数退避重试 + 降级 + 限流 + API Key | 模型挂了接口不挂 |
| 观测 | JSON 结构化日志 + trace_id + /metrics | 排障能定位到具体一步 |
| 测试 | pytest（22 例：单元 / 检索 / 接口契约） | 改代码知道有没有改坏 |
| CI | GitHub Actions（测试 + 镜像构建） | 每次 push 自动跑 |
| 部署 | Docker Compose（app + db 双容器） | 一条命令起全套 |
| 前端 | Vue3 + Vite | 三栏分开，不再把状态塞进 700 行 HTML |

---

## 效果

### 三档对照（同一批 50 题、同一个判分器，只换"给模型看什么"）

| 方案 | 准确率 | 平均延迟 | 平均上下文 | 备注 |
|---|---|---|---|---|
| A 全历史直塞 | 40/50 = **80%** | 2609ms | 859 字符 | 只调 1 次模型，最快但最贵 |
| B 纯向量 top5 | 42/50 = **84%** | 4745ms | 109 字符 | 无关键词、无保留分、无 RRF |
| C MemKeep 混合 | 42/50 = **84%** | 6060ms | **99 字符** | 三路 RRF + 类别加权 + 保留分 |

**诚实的结论**：在 **33 条记忆**这个规模上，MemKeep 的准确率与纯向量持平（84%），上下文更短（99 vs 109 字符），但延迟更高。

原因是数据量小的时候，暴力向量检索本身就够用；三路融合、保留分加权、RRF 这些设计的收益要到更大规模才会显现。这不是"没做好"，而是这套方案的适用边界——写在这里，比藏在结果里强。

如果要复现或扩规模，见 `eval/baseline.py`，改 `_all_rows` 的数据量即可。

### 九轮迭代（同一套 50 题，逐轮改一处）

| 轮次 | 改动 | 准确率 |
|---|---|---|
| v1 | 类别粗筛 | 50% |
| v2 | 混合打分 top_k=8 | 64% |
| v3 | 收紧 top_k=5 / min_score=0.28 | 62% |
| v4 | 去拒答选项 + 抽取加规则 | 72%（unknown 崩到 0） |
| v5 | 双采样并集 + 事件注日期 + 拒答词表 | 82%（unknown 回 100%） |
| v6 | 同批次合并 + update 保留旧值 | 82% |
| v7 | 中文 n-gram + 三路 RRF | 82% |
| v8 | update 去嵌套 | **84%** |

v8 分项：identity 9/10、preference 9/10、goal 3/6、event 9/10、tech 5/6、relation 4/5、unknown 3/3。

### 消融（20 题子集，每次只关掉一路召回）

| 变体 | 准确率 | 平均延迟 | 结论 |
|---|---|---|---|
| full（三路全开） | 18/20 = **90%** | 2654ms | 基准 |
| no_keyword（去关键词通道） | 17/20 = **85%** | 4340ms | **关键词是唯一可测贡献**：−5pt |
| no_rrf（去 RRF 融合，改线性加权） | 18/20 = 90% | 5279ms | 无可测差异 |
| no_base（去保留分加成） | 18/20 = 90% | 5469ms | 无可测差异 |

结论与三档对照一致：**在当前数据量下，只有关键词通道带来真实增益，RRF 与保留分是"为规模做准备"的设计，暂时体现不出收益**。20 题 × 1 题的粒度本来就粗，±1 题就是 5pt，所以这里不宣称任何一路"有效"或"无效"，只如实列出。

### 并发压测（容器内 20 并发 × 400 请求，只打读接口）

| 指标 | 值 |
|---|---|
| QPS | **113.9** |
| 错误率 | **0%** |
| P50 | 138ms |
| P95 | 372ms |
| P99 | 445ms |
| 最大 | 461ms |

限流默认 120 次/分钟：超过会直接返回 429，这是保护行为不是故障。压测时用 `MEMKEEP_RATE_LIMIT=0` 关闭。

---

## 快速开始

### 容器（推荐）

```bash
docker compose -f deploy/docker-compose.yml up -d
# 打开 http://127.0.0.1:5051
```

前置：本机 Ollama 已拉取 `qwen2.5:7b` 与 `bge-m3`。

### 本地

```bash
pip install -r requirements.txt
python run.py                       # 默认 SQLite，端口 5051，无需 Docker
MEMKEEP_DB=postgres python run.py    # 切 Postgres（需 PG 可达）
```

> Windows + 系统代理（如 Clash 占用 127.0.0.1:7899）时，WSL2 的 localhost 端口转发会整体失效，`docker compose` 的端口映射从宿主机全部 `RemoteDisconnected`（容器内部 `curl` 正常）。此时要么临时关闭系统代理，要么直接用上面的本地方式启动。

### 前端

```bash
cd frontend && npm install && npm run build   # 产物输出到 web/dist，由后端托管
```

---

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 数据库 + 模型可用性 |
| GET | `/metrics` | 请求数、错误数、P50/P95、模型失败数 |
| GET | `/docs` | 自动生成的接口文档 |
| POST | `/api/v1/chat` | 提问，返回答案 + 用了哪些记忆 + 写了什么 |
| POST | `/api/v1/ingest` | 显式写入一段对话（抽事实 → 判冲突 → 入库） |
| GET | `/api/v1/memories` | 列出活跃记忆（含保留分） |
| DELETE | `/api/v1/memories/{id}` | 软删除 |
| GET | `/api/v1/conflicts` | 冲突处理记录（覆盖 / 共存） |

鉴权：设置 `MEMKEEP_API_KEY` 后，请求需带 `X-API-Key` 或 `Authorization: Bearer <key>`。

---

## 目录

```
app/
  api/v1/            路由层（chat / memories / health）
  core/              配置、异常、日志、指标、限流、鉴权、调度
  repositories/      sqlite_repo / pg_repo（含连接池）/ factory
  services/          memory_service（编排）、scoring（保留分）
  schemas/           Pydantic 契约
core/                算法层：extractor / writer / retriever / llm
storage/             SQLite schema 与 CRUD（本地回退用）
eval/                testset / run_eval / baseline / ablation
frontend/            Vue3 + Vite
migrations/          001_init.sql（pgvector + HNSW）
deploy/              Dockerfile + docker-compose.yml
scripts/             smoke_api / load_test / migrate_sqlite_to_pg
tests/               pytest
```

---

## 设计取舍

1. **抽取走双采样并集**。单次抽取会漏（v4→v5 补回 10 分），代价是多一次调用。宁可多抽，后面有去重兜底。
2. **冲突判定保守**。只在同主体同属性、值明确不同、且有明确否定/替换语气时才 supersede，其余 coexist 留痕。误覆盖比并存更伤。
3. **向量不单独决定召回**。纯向量在短问句上会把"相关但类别错"的条目排前面，三路 + RRF 用于压这种噪声——但在小数据量下它的收益不明显，已如实写在上面。
4. **拒答是功能不是缺陷**。unknown 类题必须拒答，v4 曾因为加了拒答词表反而把 unknown 打到 0%，v5 才修回来。
5. **Postgres 与 SQLite 双轨**。算法层暂时仍跑 SQLite（写入路径稳定），读取路径与向量索引走 Postgres，写入后镜像同步。这是渐进迁移，不是最终形态。

---

## 局限

- 数据集是自造的 20 段对话 / 50 题，规模小，结论的置信度有限
- 抽取与判分都依赖同一个 7B 模型，存在系统性偏差
- 消融实验已跑（20 题子集，见上表），但样本粒度粗，±1 题即 5pt
- 多跳问题（"先问 A 再问 A 的细节"）未单独出题
- 目前单机单实例，没有分布式与读写分离

---

## 下一步

- 数据规模扩到千条级，验证 HNSW 与混合检索的真实收益（现在 33 条，暴力检索就够用）
- 抽取层换更强模型做对照，量化"模型能力 vs 检索设计"的贡献占比
- 消融扩到全量 50 题，把 20 题子集里 ±1 题的噪声压下去
