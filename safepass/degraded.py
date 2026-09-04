"""降级分支装配（issue 05 / RALPH T3）。

把"诚实降级"装配成 DegradedResult 契约：
    开发中/无数据说明（配置模板动态渲染，含识别出的警区号）
    + 替代信息（所在区域真实评级与时间模式，仅当在覆盖内；数据 Agent + 评级引擎，零 LLM）
    + 重新选择邀请（覆盖区清单来自配置别名表）
    + 通用建议（配置）与紧急资源（fixtures/safe_places 通用清单逐字段透出）

零路径级/趋势级结论、零编造：话术模板经配置集中管理，
tests/test_degraded.py 有路径级词汇黑名单断言（路线风险/照明/替代路线…）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from safepass import addressing, config_loader, contracts, data_agent, output_pipeline, rating_engine

# fixtures/safe_places/precinct_safe_places.json 相对本文件：safepass/ -> 项目根/fixtures/
SAFE_PLACES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "safe_places" / "precinct_safe_places.json"

# 评级枚举 → 面向用户标签（CONTEXT.md 词汇：🟢相对安全/🟡需注意/🔴高风险/⚪数据不足）
RATING_LABELS = {
    contracts.RATING_GREEN: "🟢 相对安全",
    contracts.RATING_YELLOW: "🟡 需注意",
    contracts.RATING_RED: "🔴 高风险",
    contracts.RATING_INSUFFICIENT: "⚪ 数据不足",
}


def load_general_venues() -> list[dict]:
    """通用紧急清单（911/311 + 五警局）逐字段读出，不做任何改写。"""
    doc = json.loads(SAFE_PLACES_PATH.read_text(encoding="utf-8"))
    return list(doc["general"]["venues"])


def covered_area_names(cfg: config_loader.AppConfig) -> list[str]:
    """重新选择邀请里的覆盖区清单：按配置别名表顺序，顺序稳定、可测。"""
    names = addressing.canonical_names(cfg)
    return [names[p] for p in names]


@dataclass(frozen=True)
class AreaAssessment:
    """单区域评估的复用结果：聚合统计 + 评级输出 + 替代信息视图 + 来源标注。

    sources 原样来自数据 Agent 聚合（spec D8：模拟数据/真实 NYPD 数据/混合），
    契约 sources 字段不得另行硬编码。
    """

    stats: data_agent.PrecinctStats
    rated: rating_engine.RatingResult
    alternative: contracts.AlternativeInfo
    sources: tuple[str, ...]


def assess_area(
    resolved: addressing.ResolvedArea,
    records: Iterable[data_agent.CrimeRecord],
    cfg: config_loader.AppConfig,
) -> AreaAssessment | None:
    """评估单一解析区域：仅当在覆盖内时返回（越界/跨警区 → None，不编造）。"""
    if not resolved.in_coverage(cfg):
        return None
    stats = data_agent.aggregate_precinct(records, resolved.precincts[0])
    rated = rating_engine.rate_precinct(stats, cfg)
    alternative = contracts.AlternativeInfo(
        precinct=stats.precinct,
        area=resolved.canonical_name,
        rating=rated.rating,
        confidence=rated.confidence,
        sample_size=stats.sample_size,
        explanation=rated.explanation,
        day_night=contracts.DayNight(day=stats.day_night.day, night=stats.day_night.night),
    )
    return AreaAssessment(stats=stats, rated=rated, alternative=alternative, sources=stats.sources)


def build_alternative_info(
    resolved: addressing.ResolvedArea,
    records: Iterable[data_agent.CrimeRecord],
    cfg: config_loader.AppConfig,
) -> contracts.AlternativeInfo | None:
    """替代信息：仅当解析区域在覆盖内时给出真实评级与时间模式（spec D3）。"""
    assessment = assess_area(resolved, records, cfg)
    return None if assessment is None else assessment.alternative


def _degraded_message(
    capability: str,
    primary: addressing.ResolvedArea | None,
    cfg: config_loader.AppConfig,
) -> str:
    """开发中/无数据说明：配置模板动态渲染 {area}/{precincts}，不写死警区号。

    primary 为 None（未能识别区域）时用 capability 对应的通用模板。
    """
    templates = cfg.degraded.explanation_templates
    if primary is None:
        key = {
            contracts.CAPABILITY_PATH: "path_generic",
            contracts.CAPABILITY_TREND: "trend_generic",
            contracts.CAPABILITY_OUT_OF_COVERAGE: "unrecognized",
        }[capability]
        template = templates.get(key)
        if template is None:
            raise config_loader.ConfigError(f"degraded.explanation_templates 缺少 {key} 模板")
        return template
    if capability == contracts.CAPABILITY_OUT_OF_COVERAGE:
        key = "multi_precinct" if len(primary.precincts) > 1 else "out_of_coverage"
    else:
        key = capability
    template = templates.get(key)
    if template is None:
        raise config_loader.ConfigError(f"degraded.explanation_templates 缺少 {key} 模板")
    return template.format(
        area=primary.canonical_name,
        precincts="/".join(str(p) for p in primary.precincts),
    )


def build_degraded_result(
    capability: str,
    primary: addressing.ResolvedArea | None,
    alternative: contracts.AlternativeInfo | None,
    cfg: config_loader.AppConfig,
    *,
    data_sources: tuple[str, ...] = (),
) -> contracts.DegradedResult:
    """装配 DegradedResult（spec D3）。primary = 触发降级的主区域（可为 None = 未识别）。

    sources 原样透出数据 Agent 来源标注（仅在真的用了数据时）；越界/未识别 = 空。
    """
    if capability not in contracts.LEGAL_CAPABILITIES:
        raise ValueError(f"非法降级能力细分：{capability!r}")
    used_data = alternative is not None
    result = contracts.DegradedResult(
        degraded_capability=capability,  # type: ignore[arg-type]
        message=_degraded_message(capability, primary, cfg),
        alternative_info=alternative,
        reselection_invitation=cfg.degraded.reselection_invitation.format(
            covered="、".join(covered_area_names(cfg))
        ),
        general_suggestions=list(cfg.degraded.general_suggestions),
        emergency_resources=load_general_venues(),  # Pydantic 逐字段校验为 Venue
        disclaimer=cfg.disclaimer,
        sources=list(data_sources) if used_data else [],
        sample_size=alternative.sample_size if used_data else None,
    )
    # 装配层确定性自检：建议结构与横切字段过同一套业务校验器（AC-006/010），
    # 配置被破坏时明确失败，绝不带病透出契约。
    output_pipeline.validate_contract(
        result,
        validators=(
            output_pipeline.make_suggestions_validator(cfg),
            output_pipeline.validate_non_empty_disclaimer,
        ),
    )
    return result
