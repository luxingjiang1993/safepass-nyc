"""L2 judge cassette 一次性录制（issue 03 / M1 人工前置项）。

真实 DashScope 调用（模型 = config eval.judge_model 锁定，temperature=0）
对 50 条金标逐条做三类判定（groundedness / hallucination / relevance），
录制进 tests/cassettes/l2_judge.json（回放零真实调用），并把逐条判定结果
落 fixtures/eval/l2_results_v1.json（回放对账 + 票 04 README 基线）。

前置：环境变量 DASHSCOPE_API_KEY（一次性真实 key；此后回放不再需要）。
用法：
    python scripts/record_l2_cassette.py            # 录制（删除旧 cassette 后重建）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # safepass 包
sys.path.insert(0, str(REPO_ROOT / "tests" / "eval"))  # l2_runner（与 pytest 同路径）

from safepass import config_loader  # noqa: E402
from safepass.llm_client import ChatResponse  # noqa: E402

import l2_runner  # noqa: E402


class DashScopeJudge:
    """LLMClient 协议适配：openai SDK 走 DashScope 兼容接入点。

    显式 http_client：本仓库 openai==1.51.2 与 httpx>=0.28 的 proxies 参数
    不兼容（venv 实测 TypeError），自建 httpx.Client 绕开 SDK 默认构造。
    """

    def __init__(self, cfg: config_loader.AppConfig):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise SystemExit(
                "缺少 DASHSCOPE_API_KEY 环境变量（一次性录制需真实 key；回放不需要）"
            )
        self._client = OpenAI(
            api_key=api_key,
            base_url=cfg.eval.base_url,
            http_client=httpx.Client(timeout=120),
        )

    def chat(self, messages, *, model=None, **kwargs):
        response = self._client.chat.completions.create(
            model=model, messages=list(messages), **kwargs
        )
        return ChatResponse(
            content=response.choices[0].message.content or "", model=response.model or ""
        )


def main() -> None:
    cfg = config_loader.load_config()
    cassette = l2_runner.cassette_path(cfg)
    if cassette.exists():
        cassette.unlink()  # 全量重录：旧交互与新提示词指纹必然不匹配，不留残骸

    judge = DashScopeJudge(cfg)
    results = l2_runner.run_l2_suite(judge_client=judge, cfg=cfg, record=True)

    l2_runner.write_results(results)
    metrics = results["metrics"]
    print(f"cassette 落盘：{cassette.relative_to(REPO_ROOT)}")
    print(f"结果工件：{l2_runner.RESULTS_PATH.relative_to(REPO_ROOT)}")
    print(
        "指标：groundedness_mean={groundedness_mean:.3f} "
        "relevance_mean={relevance_mean:.3f} hallucination_rate={hallucination_rate:.3f}".format(
            **metrics
        )
    )


if __name__ == "__main__":
    main()
