"""N2 三列生成 cassette 一次性录制（issue 26 / N2b）。

真实 DashScope 调用（模型 = config eval.judge_model，对照列 temperature=0）。
产出：

1. tests/cassettes/n2_bare.json — 裸 LLM
2. tests/cassettes/n2_rag.json — 无约束 RAG
3. tests/cassettes/n2_safepass.json — SafePass 唯一接缝管线 LLM（提取+建议）
4. fixtures/eval/n2_results_v1.json — 打分工件
5. docs/baseline-vs-safepass.md — 对照页

不写、不删 L2 cassette（l2_judge*.json / l2_skill.json）。

前置：DASHSCOPE_API_KEY（或仓库根 .env 中同名变量；不把密钥打到 stdout）。
用法：
    python scripts/record_n2_cassette.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "eval"))

from safepass import config_loader  # noqa: E402
from safepass.llm_client import ChatResponse  # noqa: E402

import n2_runner  # noqa: E402


def _load_dotenv_if_present() -> None:
    """把 .env 里尚未在进程中的键补进 environ；永不打印值。"""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class DashScopeClient:
    """与 scripts/record_l2_cassette.py 同款 OpenAI 兼容适配（评测脚本内重复，不进主路径）。"""

    def __init__(self, cfg: config_loader.AppConfig):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise SystemExit(
                "缺少 DASHSCOPE_API_KEY（一次性录制需真实 key；回放不需要）"
            )
        self._model = cfg.eval.judge_model
        self._client = OpenAI(
            api_key=api_key,
            base_url=cfg.eval.base_url,
            http_client=httpx.Client(timeout=120),
        )

    def chat(self, messages, *, model=None, **kwargs):
        response = self._client.chat.completions.create(
            model=model or self._model, messages=list(messages), **kwargs
        )
        return ChatResponse(
            content=response.choices[0].message.content or "",
            model=response.model or "",
        )


def _delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="录制 N2 三列生成 cassette")
    parser.add_argument(
        "--reuse-safepass",
        action="store_true",
        help="只重录裸 LLM / 无约束 RAG，复用已有 n2_safepass.json",
    )
    args = parser.parse_args()

    _load_dotenv_if_present()
    cfg = config_loader.load_config()
    _delete_if_exists(n2_runner.BARE_CASSETTE)
    _delete_if_exists(n2_runner.RAG_CASSETTE)
    if not args.reuse_safepass:
        _delete_if_exists(n2_runner.SAFEPASS_CASSETTE)

    client = DashScopeClient(cfg)
    results = n2_runner.run_n2_suite(
        llm_client=client,
        cfg=cfg,
        record=True,
        record_safepass=not args.reuse_safepass,
    )
    n2_runner.write_results(results)
    n2_runner.write_report(results)

    cassettes = (n2_runner.BARE_CASSETTE, n2_runner.RAG_CASSETTE, n2_runner.SAFEPASS_CASSETTE)
    print("cassettes 落盘：")
    for cassette in cassettes:
        print(f"  {cassette.relative_to(REPO_ROOT)}")
    print(f"结果工件：{n2_runner.RESULTS_PATH.relative_to(REPO_ROOT)}")
    print(f"对照页：{n2_runner.REPORT_PATH.relative_to(REPO_ROOT)}")

    closure = results["metrics"]["closure"]
    print(f"布尔收口：{closure}")
    print(f"失败样例数：{len(results['failure_samples'])}")
    if not all(closure.values()) or len(results["failure_samples"]) < 3:
        print("!!! N2b 收口未达成：不把未达标工件当完成（交回人工看逐条输出）")
        sys.exit(1)


if __name__ == "__main__":
    main()
