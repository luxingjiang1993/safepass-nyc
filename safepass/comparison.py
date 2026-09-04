"""双区对比装配（issue 08 / RALPH T6；spec D3 / F3）。

把两个覆盖内解析区域装配成 ComparisonResult 契约：
    每侧 AreaSummary（评级/样本量/昼夜分布/犯罪类型 Top5，逐字段来自
    数据 Agent 本次聚合 + 评级引擎，零 LLM、零画像——ADR-0001/0002）
    + F3-2 对比维度表（数据可支撑的维度 available；长期趋势诚实标开发中；
      人群维度随 T7 三维提取落地后扩充）
    + F3-4 决策辅助（结构层存在性断言；话术模板读集中配置，
      {area} 一律按两侧真实聚合数据填充，品味属人工抽查项）

诚实边界：任一侧为 ⚪ 数据不足时，"谁更适合"没有数据依据，
decision_aid 置 None（与 F3-5 同一诚实原则在 ⚪ 分支的延伸）。
"""

from __future__ import annotations

from typing import Iterable

from safepass import addressing, config_loader, contracts, data_agent, degraded, output_pipeline

# 评级 → 安全性排序（🟢 < 🟡 < 🔴；⚪ 不参与排序，装配层先行剔除）
_RATING_SAFETY_ORDER = {
    contracts.RATING_GREEN: 0,
    contracts.RATING_YELLOW: 1,
    contracts.RATING_RED: 2,
}

# F3-2 对比维度表（available = 本次聚合数据可支撑；in_development = 诚实标注）
_DIMENSION_STATUSES = (
    ("overall_rating", "available"),
    ("top_offense_types", "available"),
    ("night_risk", "available"),
    ("long_term_trend", "in_development"),
)


def build_comparison_result(
    resolved_areas: tuple[addressing.ResolvedArea, ...],
    records: Iterable[data_agent.CrimeRecord],
    cfg: config_loader.AppConfig,
) -> contracts.ComparisonResult:
    """装配双（多）区对比契约。调用方保证全部区域在覆盖内（D12 已先行）。"""
    if len(resolved_areas) < 2:
        raise ValueError("对比契约至少需要两个解析区域")
    assessments: list[degraded.AreaAssessment] = []
    for resolved in resolved_areas:
        assessment = degraded.assess_area(resolved, records, cfg)
        if assessment is None:  # 防御：调用方已做覆盖判定，不可达
            raise ValueError(f"区域 {resolved.area!r} 不在覆盖内，无法产出对比契约")
        assessments.append(assessment)

    sources: list[str] = []
    for a in assessments:
        for s in a.sources:
            if s not in sources:
                sources.append(s)

    result = contracts.ComparisonResult(
        areas=[
            contracts.AreaSummary(
                area=resolved.canonical_name,
                precinct=a.stats.precinct,
                rating=a.rated.rating,
                sample_size=a.stats.sample_size,
                day_night=contracts.DayNight(day=a.stats.day_night.day, night=a.stats.day_night.night),
                top5_types=[
                    contracts.OffenseCount(offense_type=t.offense_type, count=t.count)
                    for t in a.stats.top5_types
                ],
            )
            for resolved, a in zip(resolved_areas, assessments)
        ],
        dimensions=[{"dimension": name, "status": status} for name, status in _DIMENSION_STATUSES],
        decision_aid=_decision_aid(assessments, cfg),
        sources=sources,
        disclaimer=cfg.disclaimer,
    )
    # 装配层确定性自检：横切字段过同一套业务校验器（AC-010）
    output_pipeline.validate_contract(result, validators=(output_pipeline.validate_non_empty_disclaimer,))
    return result


def _decision_aid(assessments: list[degraded.AreaAssessment], cfg: config_loader.AppConfig) -> str | None:
    """F3-4 决策辅助：模板读配置，依据两侧真实评级与昼夜分布填充。

    任一侧 ⚪ → 无数据依据出"谁更适合"，返回 None（诚实原则）。
    """
    ratings = [a.rated.rating for a in assessments]
    if any(r == contracts.RATING_INSUFFICIENT for r in ratings):
        return None

    names = [a.alternative.area for a in assessments]
    parts: list[str] = []
    best = min(range(len(assessments)), key=lambda i: (_RATING_SAFETY_ORDER[ratings[i]], i))
    if all(ratings[i] == ratings[best] for i in range(len(assessments))):
        parts.append(cfg.comparison.decision_aid_rating_tie)
    else:
        parts.append(cfg.comparison.decision_aid_rating.format(area=names[best]))

    # 夜间案件占比更低 = 夜间相对更安心（交叉相乘比较，避免浮点误差）；
    # 并列时取排前者，结果确定性
    def night_share(a: degraded.AreaAssessment) -> tuple[int, int]:
        return (a.stats.day_night.night, a.stats.sample_size)

    calmest = 0
    for i in range(1, len(assessments)):
        ref = night_share(assessments[calmest])
        cur = night_share(assessments[i])
        if cur[0] * ref[1] < ref[0] * cur[1]:
            calmest = i

    first = night_share(assessments[0])
    if all(
        night_share(assessments[i])[0] * first[1] == first[0] * night_share(assessments[i])[1]
        for i in range(len(assessments))
    ):
        parts.append(cfg.comparison.decision_aid_night_tie)
    else:
        parts.append(cfg.comparison.decision_aid_night.format(area=names[calmest]))
    parts.append(cfg.comparison.decision_aid_trend_note)
    return "".join(parts)
