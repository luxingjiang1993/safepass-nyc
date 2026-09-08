"""N3 / E7 合并入口：5 条固定 query 打印契约摘要（审阅者路径）。

无 key（未注入 LLM）走确定性路径：one_liner 数据钩子 + 模板建议，
grounds 空态打印「通用建议」。有 key（生产三件套或 DASHSCOPE_API_KEY）
注入 Suggestion Skill。

用法：
    python scripts/demo_queries.py
    python scripts/demo_queries.py --open
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from safepass import config_loader, contracts, llm_wiring  # noqa: E402
from safepass.llm_client import LLMClient  # noqa: E402
from safepass.pipeline import execute_query  # noqa: E402

# grounds 空态（模板路径）打印用语——票面 P4 定案，测试按此字面量对账。
GROUNDS_EMPTY_LABEL = "通用建议"

# P4 门槛子集：安全 + 越界 + 紧急；安全/越界 query 与金标逐字对齐。
DEMO_CASES: tuple[dict[str, str], ...] = (
    {"id": "G25", "query": "上东区晚上安全吗？", "kind": "safety"},
    {"id": "G31", "query": "法拉盛晚上安全吗？", "kind": "safety"},
    {"id": "G36", "query": "唐人街晚上安全吗？", "kind": "safety"},
    {"id": "G01", "query": "哥大附近安全吗？", "kind": "degraded"},
    {"id": "E01", "query": "救命，有人持刀！", "kind": "emergency"},
)


def resolve_llm_client(
    cfg: config_loader.AppConfig | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> LLMClient | None:
    """有 key 走 Skill，无 key 返回 None（确定性路径）。

    优先生产三件套（llm_wiring 单注入点）；仅有 DASHSCOPE_API_KEY 时
    用 config llm.base_url / llm.model 补齐后走同一注入点。
    """
    cfg = cfg or config_loader.get_config()
    env: Mapping[str, str] = os.environ if environ is None else environ
    client = llm_wiring.build_llm_client_from_env(cfg, environ=env)
    if client is not None:
        return client
    dash = (env.get("DASHSCOPE_API_KEY") or "").strip()
    if not dash:
        return None
    bridged = {
        str(k): str(v) for k, v in env.items()
    }
    bridged[llm_wiring.ENV_API_KEY] = dash
    bridged[llm_wiring.ENV_BASE_URL] = (
        (env.get(llm_wiring.ENV_BASE_URL) or "").strip() or cfg.synthetic_user.base_url
    )
    bridged[llm_wiring.ENV_MODEL] = (
        (env.get(llm_wiring.ENV_MODEL) or "").strip() or cfg.synthetic_user.model
    )
    return llm_wiring.build_llm_client_from_env(cfg, environ=bridged)


def _grounds_line(result: contracts.ResponseContract) -> str:
    grounds = getattr(result, "suggestion_grounds", None)
    if grounds:
        parts = [f"{g.doc_id}:{g.quote}" for g in grounds]
        return "grounds: " + " | ".join(parts)
    return f"grounds: {GROUNDS_EMPTY_LABEL}"


def format_summary(case: Mapping[str, str], result: contracts.ResponseContract) -> str:
    """打印完整契约摘要（形态字段 + 建议来源）。"""
    lines = [
        f"=== {case['id']} {case['query']} ===",
        f"type: {result.type}",
    ]
    source = getattr(result, "suggestions_source", None)
    if source is not None:
        lines.append(f"path: {source}")
    one_liner = getattr(result, "one_liner", None)
    if one_liner:
        lines.append(f"one_liner: {one_liner}")
    rating = getattr(result, "rating", None)
    if rating is not None:
        lines.append(f"rating: {rating}")
    precinct = getattr(result, "precinct", None)
    if precinct is not None:
        lines.append(f"precinct: {precinct}")
    if result.type == "degraded":
        lines.append(f"degraded_capability: {result.degraded_capability}")
        lines.append(f"message: {result.message}")
        lines.append("general_suggestions:")
        for item in result.general_suggestions:
            lines.append(f"  - {item}")
    if result.type == "emergency":
        lines.append(f"call_911: {result.call_911_prompt}")
        lines.append(f"comfort: {result.comfort_message}")
    suggestions = getattr(result, "suggestions", None)
    if suggestions:
        lines.append("suggestions:")
        for item in suggestions:
            lines.append(f"  - {item}")
    if result.type == "safety":
        lines.append(_grounds_line(result))
    return "\n".join(lines)


def execute_demo_cases(
    *, llm_client: LLMClient | None = None
) -> list[tuple[dict[str, str], contracts.ResponseContract]]:
    out: list[tuple[dict[str, str], contracts.ResponseContract]] = []
    for case in DEMO_CASES:
        result = execute_query(case["query"], llm_client=llm_client)
        out.append((case, result))
    return out


def run_demo(*, llm_client: LLMClient | None = None) -> list[str]:
    """跑 5 条固定 query，返回待打印行（含路径声明与逐条摘要）。"""
    path_label = "skill" if llm_client is not None else "template"
    lines = [f"path: {path_label}", f"n: {len(DEMO_CASES)}"]
    for case, result in execute_demo_cases(llm_client=llm_client):
        lines.append(format_summary(case, result))
    return lines


def _open_local_page() -> None:
    from frontend.app import create_server

    cfg = config_loader.get_config()
    client = resolve_llm_client(cfg)
    server = create_server(host="127.0.0.1", port=8000, llm_client=client)
    url = "http://127.0.0.1:8000/"
    print(f"本地页：{url}（Ctrl+C 停止）")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SafePass 审阅者路径：5 条固定 query")
    parser.add_argument(
        "--open",
        action="store_true",
        help="跑完摘要后打开本地页（阻塞服务）",
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    client = resolve_llm_client()
    print("\n\n".join(run_demo(llm_client=client)))
    if args.open:
        _open_local_page()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
