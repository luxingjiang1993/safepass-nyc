"""L2 金标判定 runner（issue 03 / M1）：50 条金标 × 3 judge 逐条判定 + 指标聚合。

共享给两侧（同一事实源，保证录制与回放指纹严格一致）：

- 回放：tests/eval/test_l2_golden_set.py（cassette 离线，零真实调用）
- 录制：scripts/record_l2_cassette.py（一次性真实 DashScope，需 DASHSCOPE_API_KEY）

判定顺序固定（JUDGE_ORDER：groundedness → hallucination → relevance），cassette
按序消费，任何顺序/提示词漂移都会触发指纹校验拒放（safepass/llm_client.py）。

本目录刻意不进 pytest 默认基线（tests/conftest.py collect_ignore）：L2 套件
依赖 cassette 资产，基线 L1（tests/test_golden_set.py）保持零 cassette 依赖、
两侧互不惊扰。运行：``pytest tests/eval -q``。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from safepass import config_loader, contracts, data_agent, evaluators, intel_agent, rating_engine, routing
from safepass.llm_client import ChatResponse, LLMClient
from safepass.pipeline import execute_query
from safepass.session_state import SessionState

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
RESULTS_PATH = REPO_ROOT / "fixtures" / "eval" / "l2_results_v1.json"

# 固定判定顺序：录制与回放两侧共用，cassette 交互序号 = 条目序 × 3 + 判定序
JUDGE_ORDER = (
    evaluators.FEEDBACK_GROUNDEDNESS,
    evaluators.FEEDBACK_HALLUCINATION,
    evaluators.FEEDBACK_RELEVANCE,
)


def cassette_path(cfg: config_loader.AppConfig | None = None) -> Path:
    cfg = cfg if cfg is not None else config_loader.load_config()
    return REPO_ROOT / cfg.eval.cassette


def load_golden() -> tuple[dict[str, Any], ...]:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    entries = tuple(golden["entries"])
    if not entries:
        raise ValueError(f"金标为空：{GOLDEN_PATH}")
    return entries


class _RouteStub:
    """固定路由 stub：模拟 FC 把追问轮路由到 follow_up（零 LLM）。

    与 tests/test_golden_set.py 的同名 stub 是刻意重复（非抽象合并）：
    L1 基线必须独立于 tests/eval（本目录显式不进默认基线），
    共享导入会让基线耦合 cassette 套件的收集健康度。
    """

    def __init__(self, route: str):
        self.route = route
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(
            content=json.dumps(
                {"route": self.route, "degraded_capability": None}, ensure_ascii=False
            )
        )


def run_entry(entry: dict[str, Any]) -> contracts.ResponseContract:
    """按金标形态打唯一接缝 execute_query（与 L1 同款驱动，L2 只判输出质量）。"""
    context = entry.get("context")
    if context is None:
        return execute_query(entry["query"], profile=entry.get("profile"))
    state = SessionState.from_result(execute_query(context["base_query"]))
    stub = _RouteStub(routing.ROUTE_FOLLOW_UP)
    result = execute_query(
        entry["query"],
        profile=entry.get("profile"),
        session_state=state,
        llm_client=stub,
    )
    if stub.calls != 1:  # 追问轮只消费一次路由调用（三维提取走确定性 fallback）
        raise AssertionError(f"{entry['id']} 追问轮路由调用数异常：{stub.calls}")
    return result


def _precinct_evidence(precinct: int, cfg: config_loader.AppConfig) -> dict[str, Any]:
    """单警区证据包：与管线同一数据路径复算（权威复算，test_golden_set 同款）。

    字段覆盖回答的全部数据性声明：评级输入（样本量/犯罪率/市均值）、图表
    （top5 类型/昼夜分布）、情报装配（community_info）——judge 逐条核对时
    不因证据缺字段而把真实声明误判为无依据。
    """
    stats = data_agent.aggregate_precinct(data_agent.load_dataset(), precinct)
    rated = rating_engine.rate_precinct(stats, cfg)
    return {
        "precinct": stats.precinct,
        "population": stats.population,
        "sample_size": stats.sample_size,
        "rate_per_100k": round(stats.rate_per_100k, 4),
        "top5_types": [
            {"offense_type": t.offense_type, "count": t.count} for t in stats.top5_types
        ],
        "day_night": {"day": stats.day_night.day, "night": stats.day_night.night},
        "rating": rated.rating,
        "confidence_tier": rated.confidence,
        "ratio_to_city_mean": (
            None if rated.confidence is None else round(rated.ratio_to_city_mean, 4)
        ),
        "city_mean_per_100k": cfg.city_mean_per_100k,
        "time_range": data_agent.load_time_range(),
        "sources": sorted(stats.sources),
        "community_info": intel_agent.build_community_info(precinct, cfg),
    }


def build_evidence(entry: dict[str, Any], cfg: config_loader.AppConfig) -> dict[str, Any]:
    """judge 的【证据】槽位：回答唯一允许依赖的事实来源。

    safety/comparison：数据 Agent 聚合 + 评级引擎复算 + 情报 Agent 知识装配；
    degraded（越界/降级）：明确标注无数据支撑——回答只允许说明性话术与
    通用建议，覆盖内替代信息（如有）给出真实评级证据。
    """
    exp = entry["expect"]
    if exp["type"] == "safety":
        return {
            "kind": "safety",
            "data": _precinct_evidence(exp["precinct"], cfg),
        }
    if exp["type"] == "comparison":
        return {
            "kind": "comparison",
            "areas": [_precinct_evidence(a["precinct"], cfg) for a in exp["areas"]],
        }
    evidence: dict[str, Any] = {
        "kind": "degraded",
        "note": (
            "越界/降级查询：系统无该区域犯罪数据，回答只允许说明性话术、"
            "覆盖区域重选邀请与通用建议，不得给出任何犯罪数据性结论"
            "（评级/案件数/犯罪率/占比/趋势/路径）；回答中的警区号识别与"
            "「不在覆盖范围」说明来自地址别名表与覆盖清单，属合规内容"
        ),
        "precinct": exp["precinct"],
    }
    if exp.get("alternative_present"):
        evidence["alternative_data"] = _precinct_evidence(
            exp["alternative_precinct"], cfg
        )
    return evidence


def build_reference(entry: dict[str, Any]) -> dict[str, Any]:
    """judge 的【reference】槽位：金标 L2 标签（must_mention / must_not_claim）。"""
    return {
        "must_mention": list(entry["l2"]["must_mention"]),
        "must_not_claim": list(entry["l2"]["must_not_claim"]),
    }


def run_l2_suite(
    *,
    judge_client: LLMClient,
    cfg: config_loader.AppConfig | None = None,
    record: bool = False,
) -> dict[str, Any]:
    """50 条金标逐条判定：execute_query 产出 → 3 judge → 逐条结果 + 指标聚合。

    judge 调用一律经 cassette（路径取 config eval.cassette）：默认严格回放
    （离线零真实调用）；record=True 显式切录制（调用方须保证在线且真实
    DASHSCOPE_API_KEY 齐备，scripts/record_l2_cassette.py）。
    """
    cfg = cfg if cfg is not None else config_loader.load_config()
    cassette = str(cassette_path(cfg))
    entries = load_golden()

    per_entry: list[dict[str, Any]] = []
    all_verdicts: list[evaluators.JudgeVerdict] = []
    for entry in entries:
        result = run_entry(entry)
        outputs = json.dumps(
            result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        evidence = evaluators.dumps_slot(build_evidence(entry, cfg))
        reference = evaluators.dumps_slot(build_reference(entry))
        verdicts: dict[str, Any] = {}
        for feedback_key in JUDGE_ORDER:
            evaluator = evaluators.build_evaluator(
                feedback_key,
                judge_client=judge_client,
                cfg=cfg,
                cassette_path=cassette,
                record=record,
            )
            verdict = evaluator(
                inputs=entry["query"], outputs=outputs, evidence=evidence, reference=reference
            )
            verdicts[feedback_key] = asdict(verdict)
            all_verdicts.append(verdict)
        per_entry.append(
            {
                "id": entry["id"],
                "form": entry["form"],
                "scenario": entry["scenario"],
                "query": entry["query"],
                "expect_type": entry["expect"]["type"],
                "verdicts": verdicts,
            }
        )

    metrics = evaluators.aggregate(all_verdicts, pass_threshold=cfg.eval.pass_threshold)
    # n_entries 是套件级事实（aggregate 只见扁平判定流，不能可靠推断条目数）
    metrics["n_entries"] = len(per_entry)
    return {
        "golden_version": json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["version"],
        "metrics": metrics,
        "entries": per_entry,
    }


def write_results(results: dict[str, Any], path: Path = RESULTS_PATH) -> None:
    """判定结果工件落盘（录制侧产出；回放侧与 cassette 对账，票 04 接 README 基线）。"""
    path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
