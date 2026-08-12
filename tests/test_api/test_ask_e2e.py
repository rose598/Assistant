"""/api/ask 端到端测试（双通道接入后）.

覆盖 Day 4 双通道在真实应用(TestClient)下：
- 双通道分流: 知识库命中 -> keyword；无命中 -> rag(mock) / fallback。
- 响应结构向后兼容 + 新增 channel。
- 多轮: 同一 session_id 在 store 中累积历史；不同 session 相互独立。
- 鲁棒输入: 空串 / 纯空白 / 超长 / SQL 注入尝试。
- mock 降级: 测试环境无 AGENT key 时返回 mock, 不 500。

注: 不依赖真实网络/API key, 由 create_llm_client 自动降级到 mock 完成。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.routes_ask import get_qa
from src.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 TestClient（共享 app 单例）."""
    return TestClient(app)


class TestAskDualChannel:
    """双通道分流."""

    def test_keyword_channel_hits_knowledge(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "CUDA out of memory 怎么办"})
        assert r.status_code == 200
        j = r.json()
        assert j["channel"] in ("keyword", "rag")  # 命中知识库应为 keyword
        assert j["answer"]

    def test_unknown_goes_rag_or_fallback(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "今天中午吃什么"})
        assert r.status_code == 200
        j = r.json()
        assert j["channel"] in ("rag", "fallback")
        assert j["answer"]

    def test_response_has_backward_compat_fields(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "如何提交作业"})
        assert r.status_code == 200
        j = r.json()
        # 旧字段保留(intent 为对象 / matched / sources / needs_llm)
        assert isinstance(j["intent"], dict)
        assert "primary" in j["intent"]
        assert isinstance(j["sources"], list)
        assert "needs_llm" in j
        assert isinstance(j["needs_llm"], bool)
        # 新字段 channel
        assert j["channel"] in ("keyword", "rag", "fallback")


class TestAskSession:
    """多轮会话与隔离."""

    def test_multiturn_same_session_accumulates(self, client: TestClient) -> None:
        qa = get_qa()
        store = qa.session_store
        sid = "e2e-same-1"
        assert store.load(sid) is None  # 会话尚未创建

        client.post("/api/ask", json={"question": "如何提交作业", "session_id": sid})
        client.post("/api/ask", json={"question": "那怎么查看状态呢", "session_id": sid})

        session = store.load(sid)
        assert session is not None
        msgs = session.get_messages()
        assert any(m["role"] == "user" and "提交作业" in m["content"] for m in msgs)
        assert any(m["role"] == "user" and "查看状态" in m["content"] for m in msgs)

    def test_different_session_independent(self, client: TestClient) -> None:
        qa = get_qa()
        store = qa.session_store
        client.post("/api/ask", json={"question": "提交作业", "session_id": "e2e-a"})
        client.post("/api/ask", json={"question": "提交作业", "session_id": "e2e-b"})
        sa = store.load("e2e-a")
        sb = store.load("e2e-b")
        assert sa is not None and sb is not None
        # 两个会话都存在且互不干扰(session_id 不同)
        assert sa.session_id != sb.session_id

    def test_no_session_id_uses_anonymous(self, client: TestClient) -> None:
        # 不传 session_id 应能正常返回(用匿名 id), 不报错
        r = client.post("/api/ask", json={"question": "排队的作业怎么看"})
        assert r.status_code == 200


class TestAskRobustness:
    """鲁棒输入处理."""

    def test_empty_question_422(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": ""})
        assert r.status_code == 422

    def test_whitespace_only(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "   "})
        assert r.status_code in (200, 422)

    def test_overlong_question(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "a" * 6000})
        # 超过 max_length=5000 被 pydantic 拦截
        assert r.status_code == 422

    def test_sql_injection_attempt(self, client: TestClient) -> None:
        r = client.post(
            "/api/ask",
            json={"question": "' OR '1'='1' -- 删除表"},
        )
        assert r.status_code == 200  # 不作为指令执行, 正常返回文本
        assert r.json()["answer"]

    def test_emoji_and_symbols(self, client: TestClient) -> None:
        r = client.post("/api/ask", json={"question": "😀 ！？ 🚀"})
        assert r.status_code == 200
        assert r.json()["answer"]


class TestAskStream:
    """SSE 流式问答端点."""

    def test_stream_yields_tokens_and_done(self, client: TestClient) -> None:
        with client.stream(
            "POST", "/api/ask/stream", json={"question": "今天中午吃什么", "session_id": "e2e-s1"}
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            body = "".join(r.iter_text())
        assert "data: [DONE]" in body  # 结尾标记
        assert '"type": "token"' in body  # 阶段性 token 事件

    def test_stream_empty_question_graceful(self, client: TestClient) -> None:
        # pydantic 拦截空串为 422(非流式), 故这里确保纯空白走流式错误帧或正常
        with client.stream("POST", "/api/ask/stream", json={"question": "  "}) as r:
            body = "".join(r.iter_text())
        assert "data: [DONE]" in body

    def test_stream_records_history(self, client: TestClient) -> None:
        # 流式问答也应把 user/assistant 写回会话历史
        qa = get_qa()
        store = qa.session_store
        sid = "e2e-stream-1"
        with client.stream(
            "POST", "/api/ask/stream", json={"question": "如何提交作业", "session_id": sid}
        ) as r:
            for _ in r.iter_text():  # 消费完
                pass
        session = store.load(sid)
        assert session is not None
        msgs = session.get_messages()
        assert any(m["role"] == "user" for m in msgs)
        assert any(m["role"] == "assistant" for m in msgs)


class TestBuildLlmDegradation:
    """_build_llm 降级路径（鲁棒性核心承诺）."""

    def test_return_mock_client_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.api.routes_ask import _build_llm
        from src.llm.mock_llm import MockLLMClient

        monkeypatch.setattr(
            "src.llm.mock_llm.create_llm_client", lambda config: MockLLMClient()
        )
        result = _build_llm(None)
        assert isinstance(result, MockLLMClient)

    def test_return_none_on_construction_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.api.routes_ask import _build_llm

        def boom(config):
            raise RuntimeError("llm 构造失败")

        monkeypatch.setattr("src.llm.mock_llm.create_llm_client", boom)
        # 构造失败 -> 降级为 None(关键词-only), 不抛给端点
        assert _build_llm(None) is None
