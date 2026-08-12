# RAG 全流程架构设计（第 3 周 Day 1 交付物）

> 目标：为"关键词匹配 + LLM/RAG 兜底"的双通道问答提供架构设计与接口契约。
> 本文档定位为**接口契约**：A 依据它实现 `integrated_qa` 等，B 依据它对接
> embedding / 向量库。文中所有"已实现"均对应仓库现存代码，签名以源码为准。

---

## 一、总体架构图

```
用户问题
    │
    ▼
┌─────────────────────────┐
│  Query 理解 (A 已实现)   │  query_understanding.py
│  ├─ 停用词过滤           │    understand / rewrite_query / normalize_query
│  └─ 同义词扩展/规范化     │
└──────────┬──────────────┘
           │ 规范后的 query
           ▼
┌────────────────────────────────────────────┐
│  integrated_qa（双通道调度，Day 4 A 实现）     │
│                                             │
│  ┌──────────────┐   得分>阈值(0.8)   ┌──────┐│
│  │ ① 关键词通道   │ ───────────────▶ │ 直回 ││
│  │   (已有匹配)  │                   └──────┘│
│  └──────┬───────┘                            │
│         │ 未命中/低置信                       │
│         ▼                                    │
│  ┌──────────────┐    检索 top-3     ┌────────┐│
│  │ ② RAG 通道    │ ───────────────▶ │ 组装    ││
│  │  Retrieve   │ ◀── embed/向量库 ─ │ Augment ││
│  └──────┬───────┘  (B 负责)         └───┬────┘│
│         │                              ▼      │
│         │                        ┌────────┐    │
│         │                        │ Generate│    │  LLM (qwen-chat)
│         │                        │ (A 负责) │    │
│         └──────────────────────▶ └────────┘    │
└────────────────────────────────┬───────────────┘
                                 │  ‖LLMResponse / 流式
                                 ▼
                    ┌────────────────────────┐
                    │ 流式输出 (A 已实现)       │  streaming.py
                    │   + 对话管理 (A 已实现)   │  iter_token_text/stream_sse
                    └────────────────────────┘
```

**双通道策略（plan §3.4 / §3.2）**
- ① 关键词通道：命中且置信度 > 0.8 → 直接返回知识库答案（省 LLM 调用，目标减少 40%）。
- ② RAG + LLM 通道：未命中/低置信 → 向量检索 top-3 → 组装上下文 → LLM 生成（含幻觉检测/来源标注，Day 5 B 后处理）。

---

## 二、组件清单与归属

| 组件 | 模块 | 状态 | 负责 | 说明 |
|---|---|---|---|---|
| 查询理解 | `src/llm/query_understanding.py` | ✅ 已实现 | A | `understand/rewrite_query/normalize_query` |
| LLM 客户端 | `src/llm/client.py` + `mock_llm.py` | ✅ 已实现 | A | `LLMClientProtocol`、`create_llm_client` |
| 流式输出 | `src/llm/streaming.py` | ✅ 已实现 | A | `iter_token_text/stream_sse/sse_payload` |
| 向量化 | `src/llm/embedding.py` | ✅ Mock 已实现 | A(mock)/B(真实 BGE) | `create_embedder` 留 B 接入点 |
| 对话管理 | `src/dialog/` | ✅ 已实现 | A | `Session` + `create_session_store` |
| Prompt 模板 | `src/llm/prompts.py` | ✅ 已实现 | A | basic/rag/script/log 4 类 |
| **向量存储** | `src/llm/vector_store.py` | ⏳ 待写 | **B** | 向量库封装（ChromaDB） |
| **RAG 引擎** | `src/llm/rag_engine.py` | ⏳ 待写 | **B(检索)+A(Generate)** | 链路组装 |
| **双通道问答** | `src/llm/integrated_qa.py` | ⏳ 待写 Day 4 | **A** | 关键词↔RAG 调度 |
| **`/api/ask` 接入** | `src/api/routes_ask.py` | ⏳ 待改 Day 4 | **A** | 接真实 LLM + 多轮 |

> 分工依据 plan §2.3：真实 Embedding / 向量库 / 检索为 B 负责；Generate、调度、流式、对话为 A 负责。
> Mock 向量化（`embedding.py`）A 已做，供链路测试；B 到位后替换 `create_embedder` 即可，上层不动。

---

## 三、接口契约（新写的组件）

下方是**建议签名**，供 A 实现与 B 对接共用，以 Python `Protocol` 表达。

### 3.1 Embedder（已实现，[src/llm/embedding.py](src/llm/embedding.py)）

```python
class Embedder(Protocol):
    dim: int
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...
    # 工厂: create_embedder(config=None) -> Embedder
```

### 3.2 VectorStore（待 B 实现 / A 可先写 Mock）

```python
class VectorStore(Protocol):
    """向量库: 支持写入分块后的知识库并检索 top-k."""

    def add(self, texts: Sequence[str], metadatas: Sequence[dict] | None = None) -> int:
        """写入文本及其元数据(如 faq id/标题), 返回写入条数."""
        ...

    def search(
        self, query: str, top_k: int = 5, threshold: float = 0.0
    ) -> list[RetrievedChunk]:
        """按 query 检索, 返回降序的 top-k 命中."""
        ...

    def count(self) -> int:
        """当前库里条目数."""
        ...

@dataclass
class RetrievedChunk:
    """一条检索命中."""
    text: str          # 命中文本/FAQ 回答
    metadata: dict     # 如 {"faq_id": "faq-001", "title": "..."}
    score: float       # 相似度(可选, 0~1)
```

> B 用 ChromaDB 实现；A 可先提供基于 cosine_similarity 的内存 Mock 以便链路自闭环。
> 分块约定（plan §3.4 / config）：`chunk_size=256, overlap=32`。

### 3.3 RagEngine（链路，B 检索 + A Generate）

```python
class RagEngine(Protocol):
    """RAG 全链路: 输入问句, 返回增强后供 LLM 生成的上下文."""

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        """第1步: 向量检索 top-k. (B 主导)"""
        ...

    def augment(
        self, query: str, chunks: Sequence[RetrievedChunk], history: Sequence[dict] | None = None
    ) -> list[dict]:  # OpenAI 风格 messages: system(含知识) + 历史 + user
        """第2步: 组装 Prompt(注入检索知识 + 多轮历史). (A 主导)"""
        ...
```

### 3.4 IntegratedQA（Day 4 A 实现，核心装配点）

```python
class IntegratedQA:
    """双通道问答.""" 

    def __init__(
        self,
        keyword_matcher,          # 现有知识库关键词匹配(知库)
        engine: RagEngine,        # RAG 链路(对接 B)
        llm: LLMClientProtocol,   # create_llm_client() 所得
        session_store,            # create_session_store() 所得
        threshold: float = 0.8,   # 关键词直回阈值
    ) -> None: ...

    async def ask(
        self,
        session_id: str,
        query: str,
    ) -> AskResult:
        """主入口: 关键词->兜底 RAG/LLM, 记录对话历史."""
        ...

@dataclass
class AskResult:
    answer: str
    intent: str
    confidence: float
    channel: str                 # "keyword" | "rag"
    sources: list[str]           # 命中 FAQ id / 来源
    needs_llm: bool
```

### 3.5 与既有组件的衔接

- 查询理解：进 IntegratedQA 前先 `rewrite_query(query)`。
- LLM：`create_llm_client(config)` 返回真实(`OpenAILLMClient`)或 `MockLLMClient`；消息为 OpenAI 风格 `{"role","content"}`。
- 流式：RAG 生成时可用 `llm.stream()` + `iter_token_text`。
- 对话：`Session.add_message(role, content)` 记录 user/assistant，TTL 由 store 层管理。
- 置信度：`关键词得分 × 0.4 + LLM 语义得分 × 0.6`（plan，Day 5 `confidence.py` 实现）。

---

## 四、`/api/ask` 接入后返回结构（与现有一致，见 routes_ask.py）

```json
{
  "answer": "...",
  "intent": "error_diagnosis",
  "confidence": 0.87,
  "channel": "keyword" | "rag",
  "sources": ["faq-031"],
  "needs_llm": true | false,
  "session_id": "..."           // 多轮上下文标识
}
```

---

## 五、待办映射（据此排 Day 4+）

- [x] Day 4（A）：`integrated_qa.py` + `/api/ask` 接入真实 qwen + 多轮会话 —— **已完成 2026-08-12**
- [x] Day 4（A）：`rag_engine.py` 独立实现（retrieve/augment，基于 mock 向量库）+ `integrated_qa` 改用之 —— **已完成 2026-08-12**（8 例单测）
- [ ] Day 4（A/B 联调）：`rag_engine` 检索端替换为 B 的向量库/真实 embed 后端到端 ≤ 3s
- [ ] Day 4/5（B）：`vector_store.py`(ChromaDB) + 真实 `create_embedder`(BGE)
- [ ] Day 5（B）：`postprocess.py`(幻觉检测/来源标注) + `confidence.py`(加权置信度)
- [ ] Day 5（A）：`cache.py`(MD5(query+prompt) → Redis, 30min)
- [ ] Day 6（A/B）：50+ 集成测试 + 性能优化（A/B 实测见 ab_test）

---

## 六、风险提示（关联 project_plan §十一）

- R03（日志/格式变化）、R05（知识库与平台不一致）：以"动态事实"标注缓解。
- **RAG 冷启动**（R08）：先用关键词匹配 → 边用边积累向量，故双通道必须先落地关键词直回。
- embedding/向量库属 B，**A 侧先以 Mock 自闭环**，避免阻塞集成。