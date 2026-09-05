"""生产模型接线（票 12 / M4，spec v2「生产模型接线」）：env → DeepSeek 客户端。

生产环境经 env 注入 OpenAI 兼容端点（生产路由 = DeepSeek ``deepseek-chat``，
CLAUDE.md 模型路由表）：

- ``LLM_API_KEY``   ：供应商密钥（绝不进配置/代码，不落盘）
- ``LLM_BASE_URL``  ：OpenAI 兼容接入点（DeepSeek = https://api.deepseek.com/v1）
- ``LLM_MODEL``     ：模型名（生产 = deepseek-chat）

**单注入点**：``build_llm_client_from_env`` 是全库唯一把真实客户端接进
``pipeline.execute_query`` 的构造路径，且产出**必经**票 06 的
``BudgetFusedClient`` 包装（日预算熔断 + 请求级限流 + 成本 JSONL 上报），
不可绕过。env 三变量任一缺失 → 返回 ``None``（确定性路径：静态意图标记 +
D12 后置，离线可跑）——前端 ``llm_client=None`` 默认值因此不变，
dev/test 继续 fake/cassette。

超时等运行参数在 config ``llm`` 节（红线 1：字面量单一事实源在
config/app.yaml）；接入点/模型名按 spec 走 env 不进配置。
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import httpx
from openai import OpenAI

from safepass import config_loader
from safepass.cost_control import BudgetFusedClient
from safepass.llm_client import ChatResponse, LLMClient

ENV_API_KEY = "LLM_API_KEY"
ENV_BASE_URL = "LLM_BASE_URL"
ENV_MODEL = "LLM_MODEL"


class OpenAICompatibleClient:
    """LLMClient 协议适配：OpenAI SDK 走任意 OpenAI 兼容端点（生产 = DeepSeek）。

    显式 http_client：本仓库 openai==1.51.2 与 httpx>=0.28 的 proxies 参数
    不兼容（venv 实测 TypeError，scripts/record_l2_cassette.py 同款先例），
    自建 ``httpx.Client`` 绕开 SDK 默认构造；测试可注入 MockTransport 客户端，
    离线验证接线零真实调用（红线 5）。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client or httpx.Client(timeout=timeout_seconds),
        )

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        response = self._client.chat.completions.create(
            model=model or self._model,
            messages=list(messages),
            **kwargs,
        )
        return ChatResponse(
            content=response.choices[0].message.content or "",
            model=response.model or "",
        )


def build_llm_client_from_env(
    cfg: config_loader.AppConfig,
    *,
    environ: Mapping[str, str] | None = None,
    http_client: httpx.Client | None = None,
) -> LLMClient | None:
    """单注入点：env 三变量齐全 → 真实客户端 → 必经熔断器包装；任一缺失 → None。

    - ``environ``：可注入的环境映射（测试直注 fake env，不读进程环境）；
      默认读 ``os.environ``（生产容器 env 接线）。
    - ``http_client``：可注入的 httpx 客户端（测试走 MockTransport 离线回放，
      不烧真钱）；默认按 config ``llm.request_timeout_seconds`` 自建。
    - 空串/纯空白视为未配置（与缺失同义），不拼接半截配置。
    """
    env = os.environ if environ is None else environ
    api_key = (env.get(ENV_API_KEY) or "").strip()
    base_url = (env.get(ENV_BASE_URL) or "").strip()
    model = (env.get(ENV_MODEL) or "").strip()
    if not (api_key and base_url and model):
        return None
    inner = OpenAICompatibleClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=cfg.llm.request_timeout_seconds,
        http_client=http_client,
    )
    return BudgetFusedClient.from_config(inner, cfg)
