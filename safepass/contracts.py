"""结构化响应契约（spec D3）。

管线唯一对外输出 = 判别联合，type 字段区分响应形态（spec D3 四种 + issue 09 扩展的
guardrail 拒绝形态）：
    SafetyQueryResult    覆盖区内查询（评级、可信度、维度、建议、图表、三维提取…）
    ComparisonResult     双区对比（单边越界时越界侧只有 out_of_coverage 说明）
    EmergencyResult      紧急模式（911 引导、中文报警用语、安全场所清单…）
    DegradedResult       诚实降级（路径/趋势/越界，含 D12 确定性后置产物）
    GuardrailResult      负例防线拒绝（种族偏见转向 / 武器建议拒绝，issue 09 / T7）

横切字段：disclaimer、sources、sample_size（如有）。评级字段是枚举，不出现自由文本。

当前落地（issue 07 / T5）：四形态契约齐备（评级枚举化，业务校验在
output_pipeline 内建校验器）；SafetyQueryResult 带结构合规的建议与
one_liner；EmergencyResult 由 T5 静态模板 + 警区静态表装配（两层紧急检测）；
ComparisonResult 由 T6 追问承接/双区对比切片装配（维度表 + 决策辅助）；
DegradedResult 与最小版 SafetyQueryResult 承接 T3。
community_info 由情报 Agent 装配（issue 10 / T8）：仇恨犯罪/诈骗提醒/
中文警员/社区资源 + 来源，未记载项统一标注、社区资源只列有官方来源
（结构见 safepass/intel_agent 模块 docstring）。
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

# 评级枚举（CONTEXT.md 词汇：安全评级；不出现自由文本评级）
RATING_GREEN = "green"
RATING_YELLOW = "yellow"
RATING_RED = "red"
RATING_INSUFFICIENT = "insufficient_data"
LEGAL_RATINGS = frozenset({RATING_GREEN, RATING_YELLOW, RATING_RED, RATING_INSUFFICIENT})
# 契约层的枚举约束（结构校验即拒绝自由文本；业务层另有双保险校验器）
RatingEnum = Literal["green", "yellow", "red", "insufficient_data"]

# 降级能力细分（spec D3：degraded_capability(path|trend|out_of_coverage)）
CAPABILITY_PATH = "path"
CAPABILITY_TREND = "trend"
CAPABILITY_OUT_OF_COVERAGE = "out_of_coverage"
LEGAL_CAPABILITIES = frozenset({CAPABILITY_PATH, CAPABILITY_TREND, CAPABILITY_OUT_OF_COVERAGE})


class Venue(BaseModel):
    """安全场所/紧急资源条目（与 fixtures/safe_places 静态表同构，逐字段透出）。"""

    type: str
    name: str
    name_zh: str | None = None
    address: str | None = None
    phone: str | None = None
    hours: str | None = None
    source: str | None = None
    verified: bool | None = None


class OffenseCount(BaseModel):
    offense_type: str
    count: int


class DayNight(BaseModel):
    day: int
    night: int


class Charts(BaseModel):
    """图表数据（spec D9）：数值与数据 Agent 本次聚合逐字段一致；⚪ 时整个模块隐藏。"""

    top5_types: list[OffenseCount]
    day_night: DayNight


class AlternativeInfo(BaseModel):
    """降级响应的替代信息：所在区域的真实评级与时间模式（仅当该区域在覆盖内）。

    全部数值来自数据 Agent 聚合 + 评级引擎（ADR-0001），零 LLM、零编造。
    """

    precinct: int
    area: str
    rating: RatingEnum
    confidence: str | None = None
    sample_size: int
    explanation: str | None = None
    day_night: DayNight


class DegradedResult(BaseModel):
    """诚实降级（路径/趋势/越界）：开发中/无数据说明 + 替代信息（若在覆盖内）
    + 重新选择邀请 + 通用建议与紧急资源。零路径级/趋势级结论、零编造。"""

    type: Literal["degraded"] = "degraded"
    degraded_capability: Literal["path", "trend", "out_of_coverage"]
    message: str  # 明确的开发中/无数据说明（配置模板动态渲染）
    alternative_info: AlternativeInfo | None = None
    reselection_invitation: str
    general_suggestions: list[str] = Field(default_factory=list)
    emergency_resources: list[Venue] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)
    sample_size: int | None = None  # 无数据（越界）时为 None


class ExtractedDimensions(BaseModel):
    """三维提取（AC-002，issue 09 / T7）：区域 / 人群 / 时间。

    值为提取原文（LLM 提取层或确定性 fallback），可为 null（查询未提到）。
    三维提取只作用于个性化表述，永不进入评级输入（ADR-0001/0002）。
    """

    area: str | None = None
    crowd: str | None = None
    time: str | None = None


class SafetyQueryResult(BaseModel):
    """覆盖区内查询契约（issue 05/06，T3/T4；T7 扩充三维提取与画像声明字段）：评级（枚举）、
    可信度、样本量、一句话总结、结构合规的建议、图表、诚实缺口、来源、时效、
    紧急资源、免责声明。

    extracted：AC-002 三维提取（区域/人群/时间），每份安全契约必带（未提到的维度为 null）；
    profile_notice：AC-023 画像隐私透明声明（"会话级、关闭即删除"，单一事实源在配置）。
    community_info：情报 Agent 装配的华人社区信息（issue 10 / T8；dict 结构见
    intel_agent 模块 docstring，未记载项统一标注、社区资源只列官方来源）；
    dimensions 由细节追问叠加维度填充；建议当前来自集中配置
    （具体性/温暖度是人工抽查项）；数据不足（⚪）时 unknowns 非空、
    charts 为 null、不给评级数值与可信度。
    """

    type: Literal["safety"] = "safety"
    area: str
    precinct: int
    rating: RatingEnum
    rating_explainable_basis: float | None = None  # per-100k 与市均值倍数
    confidence_tier: str | None = None
    sample_size: int
    one_liner: str = Field(max_length=30)  # ≤30 字核心结论（AC-005；契约层结构断言）
    extracted: ExtractedDimensions
    dimensions: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    sources: list[str]
    time_range: str
    charts: Charts | None
    community_info: dict | None = None
    emergency_resources: list[Venue] = Field(default_factory=list)
    profile_notice: str = Field(min_length=1)  # AC-023 画像声明（会话级、关闭即删除）
    disclaimer: str = Field(min_length=1)


class AreaSummary(BaseModel):
    """对比形态的单区摘要：评级 + 样本量 + 夜间风险/主要犯罪类型维度的数据源。

    day_night 与 top5_types 逐字段来自数据 Agent 本次聚合（F3-2 对比维度）。"""

    area: str
    precinct: int
    rating: RatingEnum
    sample_size: int
    day_night: DayNight
    top5_types: list[OffenseCount]


class ComparisonResult(BaseModel):
    """双区对比契约（spec D3；issue 08 / T6 装配落地）。

    单边越界时整体进 DegradedResult（D12 后置 / F3-5），本形态不存在无依据对比结论。
    dimensions = F3-2 对比维度表：数据可支撑的维度标 available，长期趋势诚实标
    in_development；人群维度（女性安全）随 T7 三维提取落地后扩充。
    """

    type: Literal["comparison"] = "comparison"
    areas: list[AreaSummary] = Field(default_factory=list)
    dimensions: list[dict] = Field(default_factory=list)
    decision_aid: str | None = None  # F3-4 决策辅助话术（结构可断言，话术人工）
    sources: list[str] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)


class EmergencyResult(BaseModel):
    """紧急模式契约（spec D3；issue 07 / T5 装配落地）。

    is_emergency 恒为 true；911 引导/中文报警用语/信息清单/安抚话术为静态
    模板（config emergency.*），按警区安全场所清单（或通用清单）与 311/
    社区协助电话逐字段来自警区静态表，全程零 LLM（spec D7）。
    """

    type: Literal["emergency"] = "emergency"
    is_emergency: Literal[True] = True
    call_911_prompt: str = Field(min_length=1)
    chinese_interpreter_phrase: str = Field(min_length=1)
    info_checklist: list[str] = Field(default_factory=list, min_length=1)
    comfort_message: str = Field(min_length=1)
    venues: list[Venue] = Field(default_factory=list)
    non_emergency_contacts: list[Venue] = Field(default_factory=list)  # 311/社区协助
    sources: list[str] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)


# 负例防线拒绝形态细分（issue 09 / T7）
GUARDRAIL_BIAS = "bias_refusal"
GUARDRAIL_WEAPON = "weapon_refusal"
LEGAL_GUARDRAIL_KINDS = frozenset({GUARDRAIL_BIAS, GUARDRAIL_WEAPON})


class GuardrailResult(BaseModel):
    """负例防线拒绝契约（issue 09 / T7；判别联合第 5 形态）。

    NEG-003 种族偏见诱导 → bias_refusal：拒绝评判族裔社区，转向结构性解释
    （安全由可核实公开数据决定）；NEG-004 武器防身建议 → weapon_refusal：
    拒绝器械建议，引导合法途径。拒绝形态不携带任何评级/区域分析字段，
    绝不"边拒绝边分析"。spec D3 原文只列四种形态，本形态是 issue 09
    负例防线的实现侧扩展。

    guardrail_kind ∈ {bias_refusal, weapon_refusal}（枚举，不出现自由文本）。
    """

    type: Literal["guardrail"] = "guardrail"
    guardrail_kind: Literal["bias_refusal", "weapon_refusal"]
    message: str = Field(min_length=1)  # 拒绝 + 转向（结构性解释/合法途径），话术单一事实源在配置
    alternatives: list[str] = Field(default_factory=list)  # 可继续的合法行动路径（非器械建议）
    sources: list[str] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)


# 判别联合（spec D3 + issue 09 扩展）：管线唯一对外输出 = 五种响应形态。
ResponseContract = Union[
    SafetyQueryResult, ComparisonResult, EmergencyResult, DegradedResult, GuardrailResult
]
