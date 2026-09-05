"""管线编排与唯一接缝（spec D1）。

`execute_query(查询文本, 会话画像, 会话状态) → 结构化响应契约`
是全系统唯一测试接缝：紧急检测、意图路由、数据聚合、评级计算、
降级分支、建议生成全部在管线内部完成。

当前切片（issue 10 / RALPH T8）：情报 Agent 混合检索 + community_info 装配——
覆盖区内安全查询的 community_info（仇恨犯罪/诈骗提醒/中文警员/社区资源）
由情报 Agent 从该警区三主题知识文档确定性装配（零 LLM），未记载事实输出
统一标注（intel.unverified_label，F7-3 诚实路径），社区资源只列有官方来源
的机构（F7-4）；混合检索（FAISS 向量 + BM25 关键词，RRF 融合 top-3）作为
检索接口由检索集断言（spec D2 / CONTEXT.md 混合检索，不引入重排层）。

既有切片（issue 09 / RALPH T7）：中文地址识别扩充（别名表归配置）+ 三维提取
（AC-002：区域/人群/时间，LLM 提取层走输出控制管线，离线确定性 fallback）
+ 负例防线静态守卫（NEG-003 种族偏见 → bias_refusal 转向结构性解释；
NEG-004 武器建议 → weapon_refusal 引导合法途径；NEG-006 恐慌词黑名单装配
自检）+ 画像的合法消费（spec D5：人群标签建议排序前置、晚归时间提示
前置；评级零接触）+ 画像声明字段（AC-023）。执行序：紧急第一层 →
负例守卫 → 地址解析 → FC 路由 → 追问承接 → D12 后置 → 降级/数据查询。

既有切片（issue 08 / RALPH T6）：追问上下文承接 + 双区对比装配——
会话状态只存上轮结构化结果（地点/评级/数据摘要，spec D2/D6），
对比追问承接上轮地点走 F3 对比流程、细节追问叠加人群/时间维度重新
查询；换地点/换话题 follow_up 路由失效、走新查询流程；追问越界按
F3-5 单边越界规则（越界侧只有 out_of_coverage 说明，覆盖侧真实评级
作替代信息，无对比结论字段）。追问细分由 followup.classify 确定性
判定（配置标记，零 LLM）；双覆盖区直查对比无需 LLM 同样成立（终局
权威在数据，不在路由）。

既有切片（issue 07 / RALPH T5）：紧急检测两层 + 静态紧急组装——
第一层关键词静态表（config emergency.keywords）命中即进无 LLM 静态分支，
优先于一切 LLM 调用；第二层 FC 路由 emergency_help 兜底，路由判定后同样
不再生成自由文本；EmergencyResult 由静态模板 + 警区静态表组装（<2s）。

既有切片（issue 06 / RALPH T4）：地址解析 + FC 路由（走统一输出控制管线，
有限重试/修复/业务校验齐备）+ D12 越界判定确定性后置 + 降级分支 + 覆盖区内
最小安全查询契约（含结构合规的建议与 one_liner，装配即过业务校验）。
执行顺序（D12：越界校验发生在 FC 路由之后、数据查询之前）：
    0.  紧急检测第一层：关键词静态表命中 → 静态 EmergencyResult，零 LLM
    1.  地址解析（确定性别名表，零 LLM）
    2.  FC 路由（静态意图标记优先；注入 llm_client 时单轮 JSON 询问）
    2.5 紧急检测第二层：路由 emergency_help → 静态 EmergencyResult，零 LLM
    2.6 负例防线静态守卫（T7）：bias/weapon 标记命中 → GuardrailResult，零 LLM
        （位置在紧急两层之后：紧急兜底优先于拒绝，第二层不被遮蔽）
    3. 追问细分与承接（follow_up / area_comparison，T6）：对比追问/细节追问
       承接；换地点/换话题重置；追问对比目标越界 → F3-5 单边越界降级
    4. D12 后置校验：任一解析警区 ∉ 覆盖清单 → 无条件 DegradedResult，
       LLM 误路由也被强制改写
    5. 降级意图（path/trend）→ DegradedResult（替代信息 = 真实评级）
    6. 覆盖区内 → 数据 Agent 聚合 + 评级引擎 → SafetyQueryResult /
       ComparisonResult（≥2 区域）；SafetyQueryResult 附带情报 Agent 装配的
       community_info（T8，警区三主题知识文档确定性解析，零 LLM）
"""

from __future__ import annotations

from typing import Any

from safepass import (
    addressing,
    comparison,
    config_loader,
    contracts,
    cost_control,
    data_agent,
    degraded,
    emergency,
    extraction,
    followup,
    guardrails,
    intel_agent,
    output_pipeline,
    routing,
)
from safepass.llm_client import LLMClient
from safepass.session_state import SessionState


def execute_query(
    query_text: str,
    profile: dict[str, Any] | None = None,
    session_state: Any = None,
    *,
    llm_client: LLMClient | None = None,
) -> contracts.ResponseContract:
    """唯一接缝（spec D1）：查询文本 + 会话画像 + 会话状态 → 结构化响应契约。

    参数:
        query_text:  用户原始查询文本（中文为主）。
        profile:     会话画像（人群/时间等）；只作用于时间风险提示前置与
                     建议排序（spec D5 / ADR-0002），永不进入评级输入。
        session_state: 上轮结构化结果载体（追问上下文，spec D2/D6）；
                     换地点/换话题后由调用方以新响应重建（from_result）。
        llm_client:  可注入的 LLM 客户端（LLMClient 协议）；测试注入
                     fake/stub 或经 cassette 回放，生产包装真实 SDK。
                     消费点：FC 路由 + 三维提取（extraction.extract）。
    """
    cfg = config_loader.get_config()

    # --- 票 06 日预算熔断：熔断中的客户端视同未注入（全链路确定性降级） ---
    # 降级不静默：结构化数据照出（评级/图表/community_info 本就零 LLM），
    # 建议走配置模板文本，响应带 llm_degraded 明示标记 + degradation_notice。
    llm_degraded = False
    try:
        fused_blocked = cost_control.is_fused_blocked(llm_client)
    except cost_control.CostControlError:
        fused_blocked = True  # 预算文件损坏：fail-safe 视同熔断（LLM 降级，其余照常出）
    if fused_blocked:
        llm_client = None
        llm_degraded = True

    # --- T5 紧急检测第一层（spec D7）：关键词静态表优先于一切 LLM 调用 ---
    # 命中即进无 LLM 静态分支：EmergencyResult 由静态模板 + 警区静态表组装。
    if emergency.is_emergency(query_text, cfg):
        return emergency.build_emergency_result(
            addressing.resolve_areas(query_text, cfg), cfg
        )

    resolved = addressing.resolve_areas(query_text, cfg)
    try:
        decision = routing.route_query(query_text, llm_client, cfg)
    except cost_control.CostControlError:
        # 查询中途限流/熔断（路由 LLM 调用被拦）：路由退确定性默认
        # area_safety_query——与未注入客户端同一事实源，D12 后置兜底终局权威。
        decision = routing.RouteDecision(route=routing.ROUTE_AREA_SAFETY)
        llm_client = None
        llm_degraded = True

    # T5 紧急检测第二层（FC 路由兜底）：路由判定后同样不再生成自由文本，
    # 与第一层共用同一个静态组装入口。位置先于负例守卫与 D12：紧急响应对
    # 时间敏感且不消费数据集（D12 越界降级针对的是误路由的数据查询）。
    if decision.route == routing.ROUTE_EMERGENCY:
        return emergency.build_emergency_result(resolved, cfg)

    # --- T7 负例防线静态守卫（NEG-003/004）：零 LLM，拒绝 + 转向 ---
    # 位置在 FC 路由与紧急第二层之后：紧急兜底优先于拒绝（含"防身"的紧急
    # 描述由 emergency_help 接住进紧急模式，不被守卫截胡，spec D2/D7 第二层
    # 不被遮蔽）；守卫本身纯静态表判定。种族偏见诱导 → bias_refusal（转向
    # 结构性解释）；武器防身建议 → weapon_refusal（引导合法途径）。
    # 绝不"边拒绝边分析"。
    guardrail_kind = guardrails.check(query_text, cfg)
    if guardrail_kind is not None:
        return guardrails.build_guardrail_result(guardrail_kind, cfg)

    # --- T6 追问承接（spec D6 / F8）与双区对比（F3） ---
    # 细分由 followup.classify 确定性判定（配置标记，零 LLM）：
    # 对比追问/细节追问承接上轮结构化结果；换地点/换话题 → follow_up
    # 路由失效，走新查询流程（session_state 不复用，调用方以新响应重建）。
    # extraction_client：首轮直接查询用注入客户端走 LLM 提取层（AC-002）；
    # 追问轮一律降为 None（确定性 fallback，见下方分支注释）。
    extraction_client = llm_client
    if decision.route == routing.ROUTE_FOLLOW_UP:
        # 追问轮（含换地点/换话题重置）的三维提取一律走确定性 fallback：
        # 承接类查询的维度与 followup 细分同一事实源（标记表 + 别名表），
        # LLM 提取层只服务首轮直接查询（AC-002），追问响应零额外 LLM 调用。
        extraction_client = None
        plan = followup.classify(query_text, resolved, session_state, cfg)
        if plan.kind == followup.KIND_COMPARISON:
            if plan.target is None or session_state is None:  # 细分不变量，防御不可达
                raise ValueError("对比追问细分缺少承接目标或会话状态（followup.classify 不变量被破坏）")
            base = followup.base_resolved(session_state.last)
            return _build_comparison_with_fallback(base, (base, plan.target), cfg, llm_degraded)
        if plan.kind == followup.KIND_DETAIL:
            if session_state is None:  # 细分不变量，防御不可达
                raise ValueError("细节追问细分缺少会话状态（followup.classify 不变量被破坏）")
            base = followup.base_resolved(session_state.last)
            records = data_agent.load_dataset()
            return _build_safety_result(
                base,
                records,
                cfg,
                query_text=query_text,
                dimensions=plan.dimensions,
                # 追问轮的三维提取走确定性 fallback（extraction_client=None，
                # 零额外 LLM 调用）：承接维度与提取同源（followup 标记表），
                # LLM 提取层只服务直接查询（AC-002），追问响应更快、cassette 面更小。
                profile=profile,
                llm_degraded=llm_degraded,
            )
        # 换地点/换话题：重置，落入下方新查询统一流程（resolved 可能为空或有区域）
        session_state = None

    # AC-016 形态：已查询一个区域后直问"和X比哪个更安全"（路由 area_comparison），
    # 单区域 + 有会话状态 → 承接上轮地点组成对比；目标越界 → F3-5 单边越界降级。
    if (
        decision.route == routing.ROUTE_AREA_COMPARISON
        and len(resolved) == 1
        and session_state is not None
        and resolved[0].precincts[0] not in {s.precinct for s in session_state.areas}
    ):
        base = followup.base_resolved(session_state.last)
        return _build_comparison_with_fallback(base, (base, resolved[0]), cfg, llm_degraded)

    # --- D12 越界判定确定性后置（spec D12）：FC 路由之后、数据查询之前 ---
    # 解析出警区 ∉ 覆盖清单（含跨警区无法建模）→ 无条件 DegradedResult，
    # 即使 LLM 误路由到 area_safety_query 也被强制改写。
    out_of_coverage = next((r for r in resolved if not r.in_coverage(cfg)), None)
    if out_of_coverage is not None:
        return _single_side_ooc_degraded(out_of_coverage, resolved, cfg, llm_degraded)

    # --- 降级意图（path/trend）：零路径级/趋势级结论，替代信息给真实评级 ---
    # 未识别区域也不逃出契约：降级形态照常产出，替代信息为 None（spec D3）。
    if decision.degraded_capability in (contracts.CAPABILITY_PATH, contracts.CAPABILITY_TREND):
        records = data_agent.load_dataset()
        primary = resolved[0] if resolved else None
        assessment = (
            degraded.assess_area(primary, records, cfg) if primary is not None else None
        )
        return _mark_llm_degraded(
            degraded.build_degraded_result(
                decision.degraded_capability,
                primary,
                None if assessment is None else assessment.alternative,
                cfg,
                data_sources=() if assessment is None else assessment.sources,
            ),
            llm_degraded,
            cfg,
        )

    if not resolved:
        # 未能识别任何已知区域：诚实降级（不编造、不抛异常逃出契约）
        return _mark_llm_degraded(
            degraded.build_degraded_result(
                contracts.CAPABILITY_OUT_OF_COVERAGE, None, None, cfg
            ),
            llm_degraded,
            cfg,
        )

    # --- 覆盖区内：数据查询（聚合 + 评级） ---
    records = data_agent.load_dataset()
    if len(resolved) >= 2:
        # 双（多）覆盖区对比：终局权威在数据（F3-1），不要求 LLM 路由确认
        return _mark_llm_degraded(
            comparison.build_comparison_result(tuple(resolved), records, cfg),
            llm_degraded,
            cfg,
        )
    return _build_safety_result(
        resolved[0],
        records,
        cfg,
        query_text=query_text,
        extraction_client=extraction_client,
        profile=profile,
        llm_degraded=llm_degraded,
    )


def _single_side_ooc_degraded(
    primary: addressing.ResolvedArea,
    covered_candidates: tuple[addressing.ResolvedArea, ...],
    cfg: config_loader.AppConfig,
    llm_degraded: bool = False,
) -> contracts.DegradedResult:
    """F3-5/D12 单边越界降级的统一装配：越界侧只有 out_of_coverage 说明，
    覆盖侧（candidates 中首个覆盖内区域）的真实评级作替代信息，无对比结论。"""
    records = data_agent.load_dataset()
    assessment = next(
        (a for r in covered_candidates if (a := degraded.assess_area(r, records, cfg)) is not None),
        None,
    )
    return _mark_llm_degraded(
        degraded.build_degraded_result(
            contracts.CAPABILITY_OUT_OF_COVERAGE,
            primary,
            None if assessment is None else assessment.alternative,
            cfg,
            data_sources=() if assessment is None else assessment.sources,
        ),
        llm_degraded,
        cfg,
    )


def _build_comparison_with_fallback(
    covered_base: addressing.ResolvedArea,
    pair: tuple[addressing.ResolvedArea, addressing.ResolvedArea],
    cfg: config_loader.AppConfig,
    llm_degraded: bool = False,
) -> contracts.ResponseContract:
    """追问/直问对比的统一出口：目标越界 → F3-5 单边越界降级；
    双覆盖内 → ComparisonResult（pair 顺序 = [基准, 目标]，承接语义稳定）。"""
    target = pair[1]
    if not target.in_coverage(cfg):
        return _single_side_ooc_degraded(target, (covered_base,), cfg, llm_degraded)
    records = data_agent.load_dataset()
    return _mark_llm_degraded(
        comparison.build_comparison_result(pair, records, cfg),
        llm_degraded,
        cfg,
    )


def _mark_llm_degraded(
    result: contracts.ResponseContract,
    llm_degraded: bool,
    cfg: config_loader.AppConfig,
) -> contracts.ResponseContract:
    """票 06 降级明示：数据契约（safety/comparison/degraded）被打上
    llm_degraded 标记并携带 config 降级话术——明示降级不静默，数据字段
    不受影响。Emergency/Guardrail 形态刻意不标：其内容本就走静态模板
    （零 LLM 依赖），不存在"LLM 被降级"的语义。"""
    if llm_degraded and isinstance(
        result,
        (contracts.SafetyQueryResult, contracts.ComparisonResult, contracts.DegradedResult),
    ):
        result.llm_degraded = True
        result.degradation_notice = cfg.cost_control.degraded_notice
    return result


def _profile_text(profile: dict[str, Any] | None) -> str:
    """画像展平为可扫描文本（字符串值与字符串列表项）；None → 空串（无画像）。"""
    if not profile:
        return ""
    parts: list[str] = []
    for value in profile.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(v) for v in value if isinstance(v, str))
    return "\n".join(parts)


def _personalized_suggestions(
    base: tuple[str, ...], profile_text: str, cfg: config_loader.AppConfig
) -> list[str]:
    """画像对建议的唯一作用：人群标签命中的个性化建议排序前置（spec D5②）。

    集合边界不破：只重排、不新增条数来源；总数仍受 3-5 条结构校验约束
    （个性化建议同样来自集中配置，且不得是空话黑名单词）。
    """
    if not profile_text:
        return list(base)
    picked = [s for tag, s in cfg.profile.crowd_suggestions.items() if tag in profile_text]
    ordered = picked + [s for s in base if s not in picked]
    return ordered[: output_pipeline.SUGGESTIONS_MAX]


def _profile_time_note(
    dimensions: list[dict[str, Any]], profile_text: str, cfg: config_loader.AppConfig
) -> list[dict[str, Any]]:
    """画像对时间提示的唯一作用：晚归画像的风险提示个性化前置（spec D5①）。

    以"时间提示"维度追加呈现；评级与数据字段零接触（ADR-0002）。
    """
    if profile_text and any(m in profile_text for m in cfg.profile.late_night_markers):
        return [*dimensions, {"dimension": "时间提示", "value": cfg.profile.late_night_note}]
    return dimensions


def _build_safety_result(
    resolved: addressing.ResolvedArea,
    records: tuple[data_agent.CrimeRecord, ...],
    cfg: config_loader.AppConfig,
    *,
    query_text: str,
    dimensions: tuple[followup.Dimension, ...] = (),
    extraction_client: LLMClient | None = None,
    profile: dict[str, Any] | None = None,
    llm_degraded: bool = False,
) -> contracts.SafetyQueryResult:
    """覆盖区内单区查询的契约：评级/可信度/样本量/图表/三维提取/诚实缺口。

    dimensions = 细节追问叠加的人群/时间维度（F8-2）；extraction_client =
    AC-002 三维提取的注入客户端（None 时由确定性 fallback 产出）；
    profile = 会话画像，只作用于建议排序与时间提示（spec D5）；
    llm_degraded = 票 06 熔断/限流降级标记：提取调用被成本控制拦截时
    退确定性 fallback 并置位（降级不静默）。
    """
    profile_text = _profile_text(profile)
    try:
        extracted = extraction.extract(query_text, extraction_client, cfg)
    except cost_control.CostControlError:
        # 查询中途熔断/限流：三维提取退确定性 fallback（零额外 LLM 调用），
        # 与未注入客户端同一事实源；响应带明示降级标记。
        extracted = extraction.extract(query_text, None, cfg)
        llm_degraded = True
    assessment = degraded.assess_area(resolved, records, cfg)
    if assessment is None:  # 防御：调用方已做覆盖判定，不可达
        raise ValueError(f"区域 {resolved.area!r} 不在覆盖内，无法产出安全查询契约")
    stats, rated = assessment.stats, assessment.rated
    charts_data = data_agent.build_charts(stats, cfg)
    charts = (
        None
        if charts_data is None
        else contracts.Charts(
            top5_types=[
                contracts.OffenseCount(offense_type=t.offense_type, count=t.count)
                for t in charts_data.top5_types
            ],
            day_night=contracts.DayNight(day=charts_data.day_night.day, night=charts_data.day_night.night),
        )
    )
    insufficient = rated.confidence is None  # 强制 ⚪ 档：不给评级数值/可信度/解释
    result = contracts.SafetyQueryResult(
        area=resolved.canonical_name,
        precinct=stats.precinct,
        rating=rated.rating,
        rating_explainable_basis=None if insufficient else rated.ratio_to_city_mean,
        confidence_tier=rated.confidence,
        sample_size=stats.sample_size,
        one_liner=f"{resolved.canonical_name}：{degraded.RATING_LABELS[rated.rating]}",
        extracted=contracts.ExtractedDimensions(
            area=None if extracted is None else extracted.area,
            crowd=None if extracted is None else extracted.crowd,
            time=None if extracted is None else extracted.time,
        ),
        dimensions=_profile_time_note(
            [{"dimension": d.name, "value": d.value} for d in dimensions],
            profile_text,
            cfg,
        ),
        suggestions=_personalized_suggestions(cfg.suggestions.safety_general, profile_text, cfg),
        unknowns=[cfg.degraded.insufficient_data_message] if insufficient else [],
        sources=list(stats.sources),
        time_range=data_agent.load_time_range() or "未知时间范围",
        charts=charts,
        community_info=intel_agent.build_community_info(resolved.precincts[0], cfg),
        emergency_resources=degraded.load_general_venues(),
        profile_notice=cfg.profile.notice,
        disclaimer=cfg.disclaimer,
    )
    # 装配层确定性自检：契约产出即过同一套业务校验器（AC-005/006/010、枚举评级），
    # 配置或模板被破坏时明确失败，绝不带病透出契约；
    # NEG-006 恐慌词黑名单同样在此拦截（安全叙事不得夸大风险）。
    output_pipeline.validate_contract(
        result,
        validators=(
            output_pipeline.validate_legal_rating,
            output_pipeline.validate_one_liner,
            output_pipeline.make_suggestions_validator(cfg),
            output_pipeline.validate_non_empty_disclaimer,
            guardrails.make_no_panic_validator(cfg),
        ),
    )
    return _mark_llm_degraded(result, llm_degraded, cfg)
