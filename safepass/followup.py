"""追问承接的确定性细分（issue 08 / RALPH T6；spec D6 / F8）。

FC 路由只负责把查询路由到 ``follow_up``；路由之后的细分类别由本模块
按配置标记**确定性**判定（零 LLM，与 D12 后置校验同款思路：LLM 之上
不允许再挂一层"装作看懂了"的自由裁量）：

    对比追问（KIND_COMPARISON）  文本中出现上轮以外的新区域，
                                且命中对比标记 → 承接上轮地点 + 新区域走 F3 对比流程；
    细节追问（KIND_DETAIL）      文本中未出现新区域 → 承接上轮地点，
                                叠加文本中的人群/时间维度重新查询；
    话题漂移（KIND_TOPIC_SHIFT） 换地点（出现新区域但无对比标记）、换话题
                                （无区域也无维度标记）、一次多个新区域、
                                无会话状态可承接、有对比标记但无可比目标
                                → follow_up 路由失效，走新查询流程。

越界追问（对比目标越界）不在此裁决：由管线 D12 后置校验强制改写为
F3-5 单边越界降级（覆盖侧真实评级作替代信息，越界侧只有 out_of_coverage
说明）。
"""

from __future__ import annotations

from dataclasses import dataclass

from safepass import addressing, config_loader, session_state

KIND_COMPARISON = "comparison"
KIND_DETAIL = "detail"
KIND_TOPIC_SHIFT = "topic_shift"


@dataclass(frozen=True)
class Dimension:
    """细节追问叠加的单一维度（人群/时间）；value = 命中的标记原文。"""

    name: str
    value: str


@dataclass(frozen=True)
class FollowUpPlan:
    """追问细分结果。kind=TOPIC_SHIFT 时 target/dimensions 均为空。"""

    kind: str
    target: addressing.ResolvedArea | None = None
    dimensions: tuple[Dimension, ...] = ()


def _extract_dimensions(query_text: str, cfg: config_loader.AppConfig) -> tuple[Dimension, ...]:
    """人群/时间维度标记扫描；类别顺序固定（人群在前、时间在后），结果确定性。"""
    dims: list[Dimension] = []
    for name, markers in (("人群", cfg.followup.crowd_markers), ("时间", cfg.followup.time_markers)):
        hit = next((m for m in markers if m in query_text), None)
        if hit is not None:
            dims.append(Dimension(name=name, value=hit))
    return tuple(dims)


def base_resolved(snapshot: session_state.AreaSnapshot) -> addressing.ResolvedArea:
    """会话状态快照 → 地址解析同构对象（canonical_name 快照时已规范化）。"""
    return addressing.ResolvedArea(
        area=snapshot.area,
        canonical_name=snapshot.area,
        precincts=(snapshot.precinct,),
    )


def classify(
    query_text: str,
    resolved: tuple[addressing.ResolvedArea, ...],
    state: session_state.SessionState | None,
    cfg: config_loader.AppConfig,
) -> FollowUpPlan:
    """追问细分（spec D6）：合法追问只有两种形态，其余一律视为新查询。"""
    if state is None:
        # 无会话状态可承接：follow_up 路由失效，绝不凭空捏出基准区域
        return FollowUpPlan(kind=KIND_TOPIC_SHIFT)

    session_precincts = {snap.precinct for snap in state.areas}
    new_areas = [r for r in resolved if r.precincts[0] not in session_precincts]

    if len(resolved) >= 2:
        # 一次提到多个区域：超出两种合法追问形态，交回新查询流程统一处理
        return FollowUpPlan(kind=KIND_TOPIC_SHIFT)
    if new_areas and any(m in query_text for m in cfg.followup.comparison_markers):
        return FollowUpPlan(kind=KIND_COMPARISON, target=new_areas[0])
    if new_areas:
        # 换地点：出现了新区域但没有对比标记 → 新查询，不复用上轮结果
        return FollowUpPlan(kind=KIND_TOPIC_SHIFT)

    # 文本未提到上轮以外的新区域：对比标记无承接目标，同样交回新查询流程
    if any(m in query_text for m in cfg.followup.comparison_markers):
        return FollowUpPlan(kind=KIND_TOPIC_SHIFT)

    dimensions = _extract_dimensions(query_text, cfg)
    if not dimensions:
        # 无区域也无人群/时间维度：话题漂移，走新查询流程
        return FollowUpPlan(kind=KIND_TOPIC_SHIFT)
    return FollowUpPlan(kind=KIND_DETAIL, dimensions=dimensions)
