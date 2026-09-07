"""issue 16 / A1 验收测试：建议生成 Skill 主路径（LLM 措辞 + 数据定调）。

对应 .scratch/safepass-phase3-tickets/issues/01-a1-suggestion-skill.md 的
DoD 与 P6 开赛定案：
    1. 注入真实/fake client 时建议可区分（source=skill，与模板路径集合不同源）
    2. llm_client=None 仍出合法契约：模板建议 + grounds 字段立（空）+ 来源明示
    3. 评级比特级不变：注入 Skill 与零客户端路径的评级字段完全一致
    4. 画像永不进入请求体（ADR-0003/P6）：Skill 收到的消息不含画像文本，
       画像只在本机确定性排序前置
    5. grounds 可核对校验：引文逐字、文档集合闭合、无摘要禁止凭空引用
    6. 校验不过 → 有限重试 → 仍不过 → 确定性模板降级（suggestions_source 明示）
    7. 熔断/限流拦截建议调用 → 模板 + llm_degraded 明示（票 06 同口径）
    8. suggestions.skill_enabled 开关 = B1 两路径对照的接线点（false → 强制模板）

全部离线：fake client / cassette，零真实 API 调用。
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from pydantic import BaseModel

from safepass import config_loader, contracts, cost_control, degraded
from safepass.llm_client import ChatResponse
from safepass.output_pipeline import BusinessValidationError, OutputPipelineError
from safepass.pipeline import execute_query
from safepass.skills.suggestion import (
    SuggestionPack,
    SuggestionSnippet,
    SuggestionSkillOut,
    build_messages,
    generate,
    make_grounds_validator,
)

# 与 test_profile_invariance 同源：评级相关字段（ADR-0002：Skill 也零接触）
RATING_FIELDS = ("rating", "rating_explainable_basis", "confidence_tier", "sample_size")

_ROUTE_OUT = json.dumps({"route": "area_safety_query"}, ensure_ascii=False)
_EXTRACTION_OUT = json.dumps({"area": "上东区", "crowd": None, "time": "晚上"}, ensure_ascii=False)
_SKILL_OUT = json.dumps(
    {
        "suggestions": [
            "夜间出行优先选择照明好、人流多的主干道，避开偏僻小巷",
            "随身包放在身前视线范围内，手机不要边走边外露",
            "本区夜间案件少于白天，22 点后仍建议尽量结伴通行",
        ],
        "suggestion_grounds": [],
    },
    ensure_ascii=False,
)


class _ScriptedFakeLLM:
    """按剧本逐条返回的 fake；记录每次调用收到的完整消息列表。"""

    def __init__(self, script: list[str]):
        self._script = list(script)
        self.calls = 0
        self.seen_messages: list[list[dict[str, Any]]] = []

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        self.seen_messages.append([dict(m) for m in messages])
        if not self._script:
            raise AssertionError("fake LLM 剧本耗尽：调用次数超出预期（重试无上界？）")
        return ChatResponse(content=self._script.pop(0), model="fake")


def _rating_view(result) -> dict:
    return {f: getattr(result, f) for f in RATING_FIELDS}


def _skill_pack() -> SuggestionPack:
    """覆盖区内单区的最小输入打包（数据定调；结构上无画像字段）。"""
    return SuggestionPack(
        area="上东区",
        precinct=19,
        rating=contracts.RATING_GREEN,
        rating_label=degraded.RATING_LABELS[contracts.RATING_GREEN],
        sample_size=105,
        confidence_tier="HIGH",
        ratio_to_city_mean=0.6,
        data_sufficient=True,
        top5_types=(("CRIMINAL MISCHIEF", 21), ("PETIT LARCENY", 16)),
        day_count=62,
        night_count=43,
        extracted_area="上东区",
        extracted_crowd=None,
        extracted_time="晚上",
    )


# ---------------------------------------------------------------------------
# 1. 主路径：注入 fake client 时建议可区分；模板路径契约合法
# ---------------------------------------------------------------------------


def test_skill_path_distinguishable_with_fake_client():
    """DoD 1：注入 fake client（开关开）→ 建议来自 Skill（source=skill），
    与模板路径集合不同源；评级与 one_liner 仍是确定性产物（LLM 零接触）。"""
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT, _SKILL_OUT])
    result = execute_query("上东区晚上安全吗？", llm_client=fake)

    assert fake.calls == 3, "接缝 LLM 路径 = 路由 + 三维提取 + 建议 Skill 各 1 次"
    assert result.type == "safety"
    assert result.suggestions_source == contracts.SUGGESTIONS_SOURCE_SKILL
    assert result.suggestions == json.loads(_SKILL_OUT)["suggestions"]
    assert result.suggestion_grounds == [], "A1 无检索摘要：grounds 字段立且为空（P6）"

    plain = execute_query("上东区晚上安全吗？")
    assert plain.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert set(plain.suggestions) <= set(config_loader.load_config().suggestions.safety_general)
    assert result.suggestions != plain.suggestions, "注入 client 的建议必须可区分（DoD 1）"
    assert result.one_liner == plain.one_liner, "one_liner 是确定性模板（A3 范围外，LLM 不写）"
    assert _rating_view(result) == _rating_view(plain), "评级比特级不变（DoD 3）"


def test_no_client_template_path_contract_legal():
    """DoD 2：llm_client=None 仍出合法契约——模板建议、grounds 字段立、来源明示。"""
    result = execute_query("上东区晚上安全吗？")

    assert result.type == "safety"
    assert result.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert result.suggestion_grounds == [], "grounds 字段必须立（P6 验收硬项）"
    assert 3 <= len(result.suggestions) <= 5
    assert result.rating in contracts.LEGAL_RATINGS


# ---------------------------------------------------------------------------
# 2. 画像剔除：永不进入请求体；只在本机确定性排序（ADR-0003 / P6）
# ---------------------------------------------------------------------------


def test_profile_never_enters_skill_request():
    """P6 定案 2：六维画像不进入发给模型供应商的请求体（隐私页口径一字不改）。"""
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT, _SKILL_OUT])
    profile = {"crowd": ["带娃"], "scene": "接送孩子上学", "time": "经常加班晚归"}
    result = execute_query("上东区晚上安全吗？", profile=profile, llm_client=fake)

    all_text = "\n".join(
        m["content"] for call in fake.seen_messages for m in call
    )
    for marker in ("带娃", "接送孩子上学", "加班晚归"):
        assert marker not in all_text, f"画像标签泄漏进 LLM 请求体：{marker!r}"

    # 画像只在本机消费：人群标签命中的建议仍排序前置（spec D5②，A1 不破）
    crowd_tip = config_loader.load_config().profile.crowd_suggestions["带娃"]
    assert result.suggestions[0] == crowd_tip, "画像对 Skill 产出的本机排序前置"


# ---------------------------------------------------------------------------
# 3. grounds 可核对校验（数据定调的机器侧，Craft S2 Walk Score 可核对借鉴）
# ---------------------------------------------------------------------------


def _ground(doc_id: str, quote: str) -> dict[str, str]:
    return {"doc_id": doc_id, "quote": quote}


def _validate_out(payload: dict[str, Any], snippets=()) -> SuggestionSkillOut:
    model = SuggestionSkillOut.model_validate(payload)
    make_grounds_validator(tuple(snippets))(model)
    return model


def test_grounds_required_empty_without_snippets():
    """无检索摘要（A1 现状）时 grounds 必须为空：禁止凭空引用。"""
    valid = _validate_out({"suggestions": ["a", "b", "c"], "suggestion_grounds": []})
    assert valid.suggestion_grounds == []
    with pytest.raises(BusinessValidationError):
        _validate_out(
            {"suggestions": ["a", "b", "c"], "suggestion_grounds": [_ground("d1", "引文")]}
        )


def test_grounds_quote_verbatim_and_doc_id_closed_world():
    """引文必须逐字出现在摘要原文、doc_id 必须属于摘要文档集合（A2 就位即生效）。"""
    snippets = (SuggestionSnippet(doc_id="d1", text="夜间盗窃多发，结伴出行。"),)
    valid = _validate_out(
        {
            "suggestions": ["a", "b", "c"],
            "suggestion_grounds": [_ground("d1", "夜间盗窃多发，结伴出行。")],
        },
        snippets,
    )
    assert valid.suggestion_grounds[0].quote == "夜间盗窃多发，结伴出行。"
    with pytest.raises(BusinessValidationError, match="逐字"):
        _validate_out(
            {"suggestions": ["a", "b", "c"], "suggestion_grounds": [_ground("d1", "夜间偷盗多发")]},
            snippets,
        )
    with pytest.raises(BusinessValidationError, match="之外"):
        _validate_out(
            {"suggestions": ["a", "b", "c"], "suggestion_grounds": [_ground("d2", "结伴出行")]},
            snippets,
        )


def test_generate_preserves_grounds_when_snippets_provided():
    """A2 前置通道自检：有检索摘要时，合法引文经管线通过并透出（A1 恒空）。"""
    snippets = (SuggestionSnippet(doc_id="d1", text="夜间盗窃多发，结伴出行。"),)
    script = [
        json.dumps(
            {
                "suggestions": ["夜间结伴出行", "把包放身前", "提前告知朋友行程"],
                "suggestion_grounds": [_ground("d1", "夜间盗窃多发，结伴出行。")],
            },
            ensure_ascii=False,
        )
    ]
    cfg = config_loader.load_config()
    out = generate(
        _ScriptedFakeLLM(script), "上东区晚上安全吗？", _skill_pack(), cfg, snippets=snippets
    )
    assert out.suggestion_grounds[0].doc_id == "d1"


# ---------------------------------------------------------------------------
# 4. 降级语义：校验耗尽 / 熔断限流 / 开关关 → 模板 + 明示（不静默）
# ---------------------------------------------------------------------------


def test_skill_validation_exhaustion_falls_back_to_template():
    """P6 定案 1：校验不过 → 有限重试（1+max_retries）→ 仍不过 → 模板降级。
    响应仍是合法契约，来源明示 template，评级不受影响。"""
    cfg = config_loader.load_config()
    # 每轮重试都返回不可解析内容（剧本喂满 1+max_retries 次尝试）
    fake = _ScriptedFakeLLM(
        [_ROUTE_OUT, _EXTRACTION_OUT] + ["这不是 JSON"] * (cfg.max_retries + 1)
    )
    result = execute_query("上东区晚上安全吗？", llm_client=fake)

    assert fake.calls == 2 + cfg.max_retries + 1, "路由 + 提取 + 建议 1+max_retries 次尝试"
    assert result.type == "safety"
    assert result.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert result.suggestions == list(cfg.suggestions.safety_general)
    assert _rating_view(result) == _rating_view(execute_query("上东区晚上安全吗？"))


def test_panic_word_suggestion_fails_validation_then_template():
    """NEG-006 同源黑名单扫建议正文：恐慌建议过不了 Skill 校验，退模板。"""
    cfg = config_loader.load_config()
    panic = cfg.guardrails.panic_blacklist[0]
    panic_out = json.dumps(
        {"suggestions": [f"这里{panic}，尽快搬走", "a", "b"], "suggestion_grounds": []},
        ensure_ascii=False,
    )
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT] + [panic_out] * (cfg.max_retries + 1))
    result = execute_query("上东区晚上安全吗？", llm_client=fake)

    assert result.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert all(panic not in s for s in result.suggestions), "恐慌叙事不得透出契约"


def test_skill_fused_block_falls_back_to_template_with_marker():
    """票 06 同口径：建议调用被熔断/限流拦截 → 模板 + llm_degraded 明示，
    结构化数据（评级/图表/community_info）照出。"""
    class _FusedAtSkill(_ScriptedFakeLLM):
        def chat(self, messages, *, model=None, **kwargs):
            if self.calls >= 2:  # 第 3 次（建议 Skill）起熔断拦截
                self.calls += 1
                raise cost_control.BudgetFusedError("日预算熔断（模拟）")
            return super().chat(messages, model=model, **kwargs)

    fake = _FusedAtSkill([_ROUTE_OUT, _EXTRACTION_OUT])
    result = execute_query("上东区晚上安全吗？", llm_client=fake)

    assert result.type == "safety"
    assert result.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert result.llm_degraded, "熔断降级必须明示，不静默"
    assert result.degradation_notice == config_loader.load_config().cost_control.degraded_notice
    assert result.rating in contracts.LEGAL_RATINGS, "评级照出"
    assert result.charts is not None and result.community_info is not None, "数据照出"


def test_skill_disabled_switch_forces_template():
    """P6 定案 4 的接线：suggestions.skill_enabled=false → 同一 query 强制模板
    路径（B1 两路径同台对照用同一开关跑双侧，不引入新接缝）。"""
    cfg = config_loader.load_config()
    disabled = dataclasses.replace(
        cfg, suggestions=dataclasses.replace(cfg.suggestions, skill_enabled=False)
    )
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT, _SKILL_OUT])
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config_loader, "get_config", lambda: disabled)
    try:
        result = execute_query("上东区晚上安全吗？", llm_client=fake)
    finally:
        monkeypatch.undo()

    assert fake.calls == 2, "开关关：建议 Skill 不被调用（零额外 LLM）"
    assert result.type == "safety"
    assert result.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert result.suggestions == list(cfg.suggestions.safety_general)


# ---------------------------------------------------------------------------
# 5. 输入打包渲染：确定性纯函数、数据定调、结构上无画像
# ---------------------------------------------------------------------------


def test_build_messages_renders_data_facts_and_no_profile():
    """pack 渲染 = 纯函数：区域/评级/样本/案件/昼夜/三维逐项在文；
    pack 结构上无画像字段（ADR-0003 结构级防线）。"""
    messages = build_messages("上东区晚上安全吗？", _skill_pack())
    user = messages[1]["content"]
    for expected in (
        "上东区（警区 19）",
        "🟢 相对安全",
        "样本量 105",
        "CRIMINAL MISCHIEF 21",
        "白天 62 / 夜间 43",
        "时间=晚上",
        "检索摘要：（空",
    ):
        assert expected in user, f"数据摘要缺 {expected!r}"
    assert "画像" not in user
    assert SuggestionPack.__dataclass_fields__.keys().isdisjoint({"profile", "persona"})
    assert build_messages("上东区晚上安全吗？", _skill_pack()) == messages, "渲染必须确定"


def test_build_messages_insufficient_data_omits_case_distribution():
    """⚪ 档（数据不足）：不向模型暗示案件分布（AC-022 图表隐藏同口径），
    并明确要求建议保持通用、不做数据性断言。"""
    pack = dataclasses.replace(
        _skill_pack(),
        rating=contracts.RATING_INSUFFICIENT,
        rating_label=degraded.RATING_LABELS[contracts.RATING_INSUFFICIENT],
        ratio_to_city_mean=None,
        confidence_tier=None,
        data_sufficient=False,
        top5_types=(),
        day_count=None,
        night_count=None,
    )
    user = build_messages("布鲁克林高地安全吗？", pack)[1]["content"]
    assert "主要案件" not in user and "昼夜分布" not in user
    assert "样本不足" in user and "不做数据性断言" in user
