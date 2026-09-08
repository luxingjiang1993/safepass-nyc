"""L2 金标判定 runner（issue 03 / M1 起；issue 04 / B1 两路径对照咬合 Skill）。

共享给两侧（同一事实源，保证录制与回放指纹严格一致）：

- 回放：tests/eval/test_l2_golden_set.py（cassette 离线，零真实调用）
- 录制：scripts/record_l2_cassette.py（一次性真实 DashScope，需 DASHSCOPE_API_KEY）

判定顺序固定（JUDGE_ORDER：groundedness → hallucination → relevance），cassette
按序消费，任何顺序/提示词漂移都会触发指纹校验拒放（safepass/llm_client.py）。

B1（两路径对照，禁止测模板自嗨，P6 开赛定案）：
- Skill 路径（主）：new_query 形态注入 _SkillDispatchClient——路由静态兜底
  area_safety_query（与 L1 追问 stub 同款口径，D12 后置校验使路由不具终局
  权威），三维提取 + 建议 Skill 调用走 cassette tests/cassettes/l2_skill.json。
  主指标咬合 Skill 生成的建议（judge 口径 v5：skill 建议的事实声明参与
  groundedness/幻觉判定，见 safepass/evaluators.py）。
- 模板路径（对照）：零客户端确定性模板（suggestions_source 恒 template），
  judge 走独立 cassette tests/cassettes/l2_judge_template.json。
- 主指标口径 = Skill 覆盖子集（suggestions_source=skill 的条目；eligible =
  24 条 new_query 安全查询，Skill 校验耗尽降级模板的条目进 marker，覆盖数
  受 config eval.skill_coverage_min 护栏）；模板降级路径（追问/越界/对比
  26 条 + Skill 校验降级条目，Skill 在管线设计上结构性不参与——追问轮零
  额外 LLM、降级/对比无建议 Skill）单独 marker，不计入主 groundedness。
- 两路径对照数字进 fixtures/eval/l2_results_v1.json 与 README（票 04），
  收口条件 = 主指标 Skill ≥ 模板（tests/eval 断言，非散文）。

本目录刻意不进 pytest 默认基线（tests/conftest.py collect_ignore）：L2 套件
依赖 cassette 资产，基线 L1（tests/test_golden_set.py）保持零 cassette 依赖、
两侧互不惊扰。运行：``pytest tests/eval -q``。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from safepass import config_loader, contracts, data_agent, evaluators, intel_agent, rating_engine, routing
from safepass.llm_client import ChatResponse, LLMClient, chat_with_cassette
from safepass.pipeline import execute_query
from safepass.session_state import SessionState

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
RESULTS_PATH = REPO_ROOT / "fixtures" / "eval" / "l2_results_v1.json"

# L2 测试世界单一事实源（验收审计问题 #1）：金标期望、L1 复算、cassette 指纹
# 全部建立在 mock 数据集上（tests/conftest.py 同款钉子，两处同值）。录制脚本
# 不经 pytest conftest，若任由默认解析（config runtime_dataset_path = 真实
# 数据集）会同时污染 outputs（execute_query 现场产出）与 evidence（judge 请求
# 内嵌文本）→ 录出的 cassette 与回放世界漂移、指纹全失效（票 07 事故重演）。
# 模块导入即钉死：录制/回放两侧共用本 runner，世界一致与入口无关。
MOCK_DATASET_PATH = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"
os.environ[data_agent.DATASET_PATH_ENV] = str(MOCK_DATASET_PATH)

# 固定判定顺序：录制与回放两侧共用，cassette 交互序号 = 条目序 × 3 + 判定序
JUDGE_ORDER = (
    evaluators.FEEDBACK_GROUNDEDNESS,
    evaluators.FEEDBACK_HALLUCINATION,
    evaluators.FEEDBACK_RELEVANCE,
)

# Skill 覆盖子集（B1 主指标口径）：new_query 形态的安全查询是唯一在管线设计上
# 消费建议 Skill 的条目（pipeline._build_safety_result 的 extraction_client 注入
# 点）。追问轮三维提取/建议双降零 LLM（AC-002 政策）、降级与对比形态无建议
# Skill——这三类在 Skill 路径下恒走模板，即「模板降级路径」。
SKILL_FORM = "new_query"
SKILL_EXPECT_TYPE = "safety"

# 调度锚点：各层 system 提示词的唯一子串由公开常量同源导出
# （routing.ROUTING_SYSTEM_MARKER 等）。路由调用在 L2 世界走静态兜底，
# 不回 cassette、不产生真实调用。


def cassette_path(cfg: config_loader.AppConfig | None = None) -> Path:
    cfg = cfg if cfg is not None else config_loader.load_config()
    return REPO_ROOT / cfg.eval.cassette


def template_judge_cassette_path(cfg: config_loader.AppConfig | None = None) -> Path:
    """模板对照路径的 judge cassette（B1 两路径对照的第二份 judge 录制）。"""
    cfg = cfg if cfg is not None else config_loader.load_config()
    return REPO_ROOT / cfg.eval.cassette_template


def skill_cassette_path(cfg: config_loader.AppConfig | None = None) -> Path:
    """Skill 路径管线 LLM 调用（三维提取 + 建议生成）的 cassette（B1）。"""
    cfg = cfg if cfg is not None else config_loader.load_config()
    return REPO_ROOT / cfg.eval.cassette_skill


def load_golden() -> tuple[dict[str, Any], ...]:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    entries = tuple(golden["entries"])
    if not entries:
        raise ValueError(f"金标为空：{GOLDEN_PATH}")
    return entries


def skill_subset_ids(entries: Sequence[dict[str, Any]]) -> list[str]:
    """Skill eligible 子集（B1）：金标形态上可能经建议 Skill 的条目 id。

    与运行时建议来源对账：run_l2_suite 断言实际 skill 来源 ⊆ 本子集，
    且覆盖数 ≥ config eval.skill_coverage_min（Skill 校验耗尽降级模板的
    条目进模板降级 marker，主指标分母 = 实际 skill 来源数，不静默缩水）。
    """
    return [
        e["id"]
        for e in entries
        if e["form"] == SKILL_FORM and e["expect"]["type"] == SKILL_EXPECT_TYPE
    ]


def _is_routing_call(messages: Sequence[dict[str, Any]]) -> bool:
    """判定本轮调用是否 FC 路由询问（system 消息含路由助手提示词锚点）。"""
    system = next((m for m in messages if m.get("role") == "system"), None)
    return system is not None and routing.ROUTING_SYSTEM_MARKER in str(system.get("content", ""))


class _SkillDispatchClient:
    """Skill 路径注入客户端：路由静态兜底；提取/建议调用走 cassette。

    路由在 L2 世界不是评估对象（D12 确定性后置使其不具终局权威，L1 金标已
    锁路由行为），静态回 area_safety_query 与未注入客户端同口径、零 cassette
    交互；被评估对象——建议 Skill 的输入（三维提取）与产出（建议）——经
    chat_with_cassette：录制侧真实调用落盘，回放侧零真实调用、指纹严格匹配。
    """

    def __init__(
        self,
        inner: LLMClient,
        cassette_path: Path,
        *,
        record: bool,
    ):
        self._inner = inner
        self._cassette = cassette_path
        self._record = record
        self.cassette_calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        if _is_routing_call(messages):
            return ChatResponse(
                content=json.dumps(
                    {"route": routing.ROUTE_AREA_SAFETY, "degraded_capability": None},
                    ensure_ascii=False,
                ),
                model="static-route",
            )
        self.cassette_calls += 1
        return chat_with_cassette(
            self._inner,
            self._cassette,
            messages,
            model=model,
            record=self._record,
            **kwargs,
        )


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


def run_entry(
    entry: dict[str, Any],
    *,
    skill_client: LLMClient | None = None,
) -> contracts.ResponseContract:
    """按金标形态打唯一接缝 execute_query（与 L1 同款驱动，L2 只判输出质量）。

    skill_client 非空 = Skill 路径（new_query 的提取+建议经注入客户端）；
    None = 模板路径（零客户端全确定性）。追问轮两路径同款：注入固定路由
    stub（管线内三维提取/建议双降确定性，AC-002 政策）。
    """
    context = entry.get("context")
    if context is None:
        return execute_query(
            entry["query"], profile=entry.get("profile"), llm_client=skill_client
        )
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


def _outputs_json(result: contracts.ResponseContract) -> str:
    """judge 的 outputs 槽位：完整契约逐字段进入。

    B1 起不再排除 suggestion_grounds / suggestions_source：judge 口径 v5
    按 suggestions_source 判定建议是否参与 groundedness/幻觉（模板豁免、
    Skill 参与），suggestion_grounds 是建议依据标注（引文本身不构成声明）。
    """
    return json.dumps(
        result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    )


def _precinct_evidence(precinct: int, cfg: config_loader.AppConfig) -> dict[str, Any]:
    """单警区证据包：与管线同一数据路径复算（权威复算，test_golden_set 同款）。

    字段覆盖回答的全部数据性声明：评级输入（样本量/犯罪率/市均值）、图表
    （top5 类型/昼夜分布）、情报装配（community_info）——judge 逐条核对时
    不因证据缺字段而把真实声明误判为无依据。

    数据输入显式钉 mock 世界快照（MOCK_DATASET_PATH 传参，优先级高于 env），
    与 execute_query 产出的 outputs 同一世界——录制侧不经 pytest conftest，
    这是审计问题 #1 的修复点（证据/输出跨世界漂移 → cassette 指纹失效）。
    """
    records = data_agent.load_dataset(MOCK_DATASET_PATH)
    stats = data_agent.aggregate_precinct(records, precinct)
    rating_cfg = data_agent.rating_config(records, cfg)
    rated = rating_engine.rate_precinct(stats, rating_cfg)
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
        "city_mean_per_100k": rating_cfg.city_mean_per_100k,
        "time_range": data_agent.load_time_range(MOCK_DATASET_PATH),
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
    """judge 的【reference】槽位：金标 L2 标签（must_mention / must_not_claim）。

    B1 起标签对准建议与 one_liner：must_not_claim 直接约束 Skill 建议的
    声明边界（保证类/对比类/路径级），must_mention 覆盖建议轴的要求
    （针对该区域的安全建议等）。
    """
    return {
        "must_mention": list(entry["l2"]["must_mention"]),
        "must_not_claim": list(entry["l2"]["must_not_claim"]),
    }


def _run_path(
    entries: Sequence[dict[str, Any]],
    *,
    judge_client: LLMClient,
    cfg: config_loader.AppConfig,
    judge_cassette: Path,
    skill_client: LLMClient | None,
    record: bool,
) -> dict[str, Any]:
    """单路径逐条判定：execute_query 产出 → 3 judge → 逐条结果 + 指标聚合。

    守卫（录制/回放两侧同值）：响应形态必须与金标 expect 一致——Skill 路径
    若路由/管线漂移产出错形态（如安全查询被降级），录制当场失败，绝不把
    错形态交给 judge。
    """
    per_entry: list[dict[str, Any]] = []
    all_verdicts: list[evaluators.JudgeVerdict] = []
    for entry in entries:
        result = run_entry(entry, skill_client=skill_client)
        if result.type != entry["expect"]["type"]:
            raise AssertionError(
                f"{entry['id']} 响应形态 {result.type!r} 与金标 expect "
                f"{entry['expect']['type']!r} 不一致（Skill 路径路由/管线漂移）"
            )
        outputs = _outputs_json(result)
        evidence = evaluators.dumps_slot(build_evidence(entry, cfg))
        reference = evaluators.dumps_slot(build_reference(entry))
        verdicts: dict[str, Any] = {}
        for feedback_key in JUDGE_ORDER:
            evaluator = evaluators.build_evaluator(
                feedback_key,
                judge_client=judge_client,
                cfg=cfg,
                cassette_path=str(judge_cassette),
                record=record,
            )
            verdict = evaluator(
                inputs=entry["query"], outputs=outputs, evidence=evidence, reference=reference
            )
            verdicts[feedback_key] = asdict(verdict)
            all_verdicts.append(verdict)
        suggestions_source = (
            result.suggestions_source
            if isinstance(result, contracts.SafetyQueryResult)
            else contracts.SUGGESTIONS_SOURCE_TEMPLATE
        )
        per_entry.append(
            {
                "id": entry["id"],
                "form": entry["form"],
                "scenario": entry["scenario"],
                "query": entry["query"],
                "expect_type": entry["expect"]["type"],
                "suggestions_source": suggestions_source,
                "verdicts": verdicts,
            }
        )

    metrics = evaluators.aggregate(all_verdicts, pass_threshold=cfg.eval.pass_threshold)
    # n_entries 是套件级事实（aggregate 只见扁平判定流，不能可靠推断条目数）
    metrics["n_entries"] = len(per_entry)
    return {"metrics": metrics, "entries": per_entry}


def _subset_metrics(
    per_entry: Sequence[dict[str, Any]],
    *,
    subset_ids: Sequence[str],
    cfg: config_loader.AppConfig,
) -> dict[str, Any]:
    """条目子集的指标聚合：重建判定流后走同一 aggregate（口径与全量一致）。"""
    ids = set(subset_ids)
    verdicts = [
        evaluators.JudgeVerdict(**v)
        for e in per_entry
        if e["id"] in ids
        for v in e["verdicts"].values()
    ]
    metrics = evaluators.aggregate(verdicts, pass_threshold=cfg.eval.pass_threshold)
    metrics["n_entries"] = len(ids)
    return metrics


def run_l2_suite(
    *,
    judge_client: LLMClient,
    cfg: config_loader.AppConfig | None = None,
    record: bool = False,
) -> dict[str, Any]:
    """两路径同台对照（B1）：Skill 路径（主）+ 模板路径（对照）各跑 50 条金标。

    - 主指标 metrics = Skill 覆盖子集（suggestions_source=skill 的条目，覆盖
      数受 config eval.skill_coverage_min 护栏）的判定聚合；模板降级路径
      单列 metrics_template_fallback，不计入主 groundedness；
    - template_path.metrics = 同一 Skill 覆盖子集跑确定性模板路径的对照数字；
    - comparison.comparison_ok = 收口条件（主指标 Skill ≥ 模板）的机器判定
      （groundedness/relevance 取 ≥，hallucination 取 ≤）。

    judge 与 Skill 调用一律经 cassette（路径取 config eval.*）：默认严格回放
    （离线零真实调用）；record=True 显式切录制（调用方须保证在线且真实
    DASHSCOPE_API_KEY 齐备，scripts/record_l2_cassette.py）。
    """
    cfg = cfg if cfg is not None else config_loader.load_config()
    entries = load_golden()

    skill_client = _SkillDispatchClient(
        judge_client, skill_cassette_path(cfg), record=record
    )
    skill = _run_path(
        entries,
        judge_client=judge_client,
        cfg=cfg,
        judge_cassette=cassette_path(cfg),
        skill_client=skill_client,
        record=record,
    )
    template = _run_path(
        entries,
        judge_client=judge_client,
        cfg=cfg,
        judge_cassette=template_judge_cassette_path(cfg),
        skill_client=None,
        record=record,
    )

    # 主指标口径（B1）：分母 = Skill 路径下 suggestions_source=skill 的条目
    # （金标形态 eligible 子集的实际成功者）。Skill 校验耗尽降级模板的条目
    # 与结构性不参与的条目（追问/越界/对比）同进模板降级 marker。护栏：
    # skill 覆盖数 ≥ config eval.skill_coverage_min——Skill 系统性回归时
    # 明确失败，主指标分母绝不静默缩水。
    eligible_ids = skill_subset_ids(entries)
    skill_sourced_ids = [
        e["id"]
        for e in skill["entries"]
        if e["suggestions_source"] == contracts.SUGGESTIONS_SOURCE_SKILL
    ]
    if not set(skill_sourced_ids) <= set(eligible_ids):
        raise AssertionError(
            "Skill 来源漂移：eligible 之外出现 skill 来源："
            f"{sorted(set(skill_sourced_ids) - set(eligible_ids))}"
        )
    if len(skill_sourced_ids) < cfg.eval.skill_coverage_min:
        raise AssertionError(
            f"Skill 覆盖 {len(skill_sourced_ids)}/{len(eligible_ids)} 低于护栏 "
            f"{cfg.eval.skill_coverage_min}（Skill 系统性回归，先修再录）"
        )
    fallback_ids = [e["id"] for e in entries if e["id"] not in skill_sourced_ids]

    main_metrics = _subset_metrics(skill["entries"], subset_ids=skill_sourced_ids, cfg=cfg)
    fallback_metrics = _subset_metrics(skill["entries"], subset_ids=fallback_ids, cfg=cfg)
    template_metrics = _subset_metrics(
        template["entries"], subset_ids=skill_sourced_ids, cfg=cfg
    )
    comparison_ok = {
        evaluators.FEEDBACK_GROUNDEDNESS: (
            main_metrics["groundedness_mean"] >= template_metrics["groundedness_mean"]
        ),
        evaluators.FEEDBACK_HALLUCINATION: (
            main_metrics["hallucination_rate"] <= template_metrics["hallucination_rate"]
        ),
        evaluators.FEEDBACK_RELEVANCE: (
            main_metrics["relevance_mean"] >= template_metrics["relevance_mean"]
        ),
    }
    return {
        "golden_version": json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["version"],
        "metrics": main_metrics,
        "metrics_all_entries": skill["metrics"],
        "metrics_template_fallback": fallback_metrics,
        "entries": skill["entries"],
        "template_path": {
            "metrics": template_metrics,
            "metrics_all_entries": template["metrics"],
            "entries": template["entries"],
        },
        "comparison": {
            "skill_eligible_ids": eligible_ids,
            "skill_sourced_ids": skill_sourced_ids,
            "fallback_ids": fallback_ids,
            "skill_cassette_interactions": skill_client.cassette_calls,
            "skill_metrics": main_metrics,
            "template_metrics": template_metrics,
            "comparison_ok": comparison_ok,
        },
    }


def write_results(results: dict[str, Any], path: Path = RESULTS_PATH) -> None:
    """判定结果工件落盘（录制侧产出；回放侧与 cassette 对账，票 04 接 README 基线）。"""
    path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
