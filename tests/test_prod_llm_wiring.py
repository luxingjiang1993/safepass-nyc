"""生产模型接线测试（票 12 / M4，spec v2「生产模型接线」）。

覆盖票据勾选项：
- env 注入路径有测试：fake key/base_url/model 注入验证接线（请求经
  httpx.MockTransport 离线回放，不断言真实网络、不烧真钱）；
- 注入客户端必经熔断器（单注入点，不可绕过）：工厂产出恒为
  BudgetFusedClient 包装，裸 OpenAICompatibleClient 无注入路径；
- dev/test 行为不变：env 缺失/不全 → 工厂返回 None（确定性路径）；
  前端 llm_client=None 默认值不变，fake/cassette 离线全绿（全量套件兜底）。

所有用例显式注入 environ，不读进程环境——任何机器上结果一致
（红线 2/5：可复现、离线可跑）。
"""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from frontend import app
from safepass import config_loader, cost_control, llm_wiring, pipeline
from safepass.cost_control import BudgetFusedClient
from safepass.llm_client import ChatResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_CFG = config_loader.load_config()

FAKE_ENV = {
    "LLM_API_KEY": "sk-fake-test-key",
    "LLM_BASE_URL": "https://api.deepseek.test/v1",
    "LLM_MODEL": "deepseek-chat",
}


class _RecordingTransport:
    """MockTransport 包装：录制末次请求（URL/头/体），离线回放固定响应。"""

    def __init__(self, content: str = "接线成功") -> None:
        self.requests: list[httpx.Request] = []
        self._content = content

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": self._content},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


class _ScriptedFake:
    """剧本 fake（tests/test_cost_control.py 同款）：区分路由/提取两种调用。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        system = messages[0]["content"]
        if "路由助手" in system:
            return ChatResponse(
                content=json.dumps({"route": "area_safety_query"}, ensure_ascii=False),
                model="deepseek-chat",
            )
        return ChatResponse(
            content=json.dumps({"area": None, "crowd": None, "time": None}, ensure_ascii=False),
            model="deepseek-chat",
        )


class TestEnvInjection:
    def test_no_env_returns_none(self):
        assert llm_wiring.build_llm_client_from_env(_CFG, environ={}) is None

    @pytest.mark.parametrize(
        "partial",
        [
            {"LLM_API_KEY": "sk-fake"},  # 只有 key
            {"LLM_BASE_URL": FAKE_ENV["LLM_BASE_URL"], "LLM_MODEL": "deepseek-chat"},  # 缺 key
            {**FAKE_ENV, "LLM_MODEL": "   "},  # 空白视为未配置
        ],
    )
    def test_partial_env_returns_none(self, partial):
        assert llm_wiring.build_llm_client_from_env(_CFG, environ=partial) is None

    def test_full_env_returns_fused_client(self):
        client = llm_wiring.build_llm_client_from_env(_CFG, environ=FAKE_ENV)
        # 单注入点：产出必经票 06 熔断器包装，裸客户端不可绕过
        assert isinstance(client, BudgetFusedClient)
        assert isinstance(client.inner, llm_wiring.OpenAICompatibleClient)

    def test_wired_chat_goes_through_fuse_and_reports_cost(self, tmp_path, monkeypatch):
        """fake key 全链路接线：请求头/体正确 → 响应解析 → 成本 JSONL 落盘。"""
        # 上报文件重定向到 tmp（report_path = PROJECT_ROOT / config 相对路径，
        # 补丁模块级锚点；日预算仍读真实 token-budget.json = $5，远低于熔断）
        monkeypatch.setattr(cost_control, "PROJECT_ROOT", tmp_path)
        transport = _RecordingTransport(content="你好，这里是接线测试")
        client = llm_wiring.build_llm_client_from_env(
            _CFG, environ=FAKE_ENV, http_client=transport.http_client()
        )
        assert client is not None

        response = client.chat([{"role": "user", "content": "上东区安全吗"}])

        assert response.content == "你好，这里是接线测试"
        assert response.model == "deepseek-chat"
        # 接线验证：请求确实打到 OpenAI 兼容端点的 chat/completions，密钥进头
        (request,) = transport.requests
        assert str(request.url).endswith("/chat/completions")
        assert request.headers["Authorization"] == f"Bearer {FAKE_ENV['LLM_API_KEY']}"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "deepseek-chat"
        # 成本上报（票 06 包装器职责）：JSONL 落盘且字段齐全
        report = tmp_path / _CFG.cost_control.report_path
        lines = [json.loads(l) for l in report.read_text(encoding="utf-8").splitlines() if l]
        assert len(lines) == 1
        entry = lines[0]
        assert entry["model"] == "deepseek-chat"
        assert entry["calls"] == 1
        assert entry["est_cost_usd"] > 0
        assert entry["daily_cumulative_usd"] >= entry["est_cost_usd"]

    def test_chat_model_kwarg_overrides_env_default(self):
        """显式 model 参数优先（L2 judge 等复用同协议的调用路径不受影响）。"""
        transport = _RecordingTransport()
        raw = llm_wiring.OpenAICompatibleClient(
            api_key=FAKE_ENV["LLM_API_KEY"],
            base_url=FAKE_ENV["LLM_BASE_URL"],
            model=FAKE_ENV["LLM_MODEL"],
            timeout_seconds=_CFG.llm.request_timeout_seconds,
            http_client=transport.http_client(),
        )
        raw.chat([{"role": "user", "content": "hi"}], model="qwen-turbo")
        body = json.loads(transport.requests[0].content.decode("utf-8"))
        assert body["model"] == "qwen-turbo"


def _serve(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return thread


def _get(srv, path: str) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(srv.server_address[0], srv.server_address[1], timeout=60)
    conn.request("GET", path)
    resp = conn.getresponse()
    resp.body = resp.read().decode("utf-8")  # type: ignore[attr-defined]
    conn.close()
    return resp


class TestFrontendWiring:
    """前端 app：llm_client=None 默认值不变（票 12 勾选项 3）；注入可透传。"""

    def _spy_execute_query(self, monkeypatch):
        recorded: dict[str, object] = {}
        real = pipeline.execute_query

        def spy(query_text, *, profile=None, session_state=None, llm_client=None):
            recorded["llm_client"] = llm_client
            return real(
                query_text,
                profile=profile,
                session_state=session_state,
                llm_client=llm_client,
            )

        monkeypatch.setattr(pipeline, "execute_query", spy)
        return recorded

    def test_default_server_passes_none_llm_client(self, monkeypatch):
        recorded = self._spy_execute_query(monkeypatch)
        srv = app.create_server(port=0)
        thread = _serve(srv)
        try:
            resp = _get(srv, f"/query?q={quote('上东区')}")
            assert resp.status == 200
            assert recorded["llm_client"] is None  # 默认确定性路径，离线可跑
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=5)

    def test_injected_llm_client_reaches_seam(self, monkeypatch):
        recorded = self._spy_execute_query(monkeypatch)
        fake = _ScriptedFake()
        srv = app.create_server(port=0, llm_client=fake)
        thread = _serve(srv)
        try:
            resp = _get(srv, f"/query?q={quote('上东区')}")
            assert resp.status == 200
            assert recorded["llm_client"] is fake  # 注入透传到唯一接缝
            assert fake.calls > 0  # 且真的被调用（LLM 路径生效）
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=5)
