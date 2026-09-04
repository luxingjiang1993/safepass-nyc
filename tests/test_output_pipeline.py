"""issue 06 / RALPH T4 验收测试：输出控制管线集 + 契约四形态横切字段。

对应 .scratch/safepass-nyc-mvp/issues/06-fc-routing-output-pipeline.md 六条勾选：
    1. 输出控制管线集：注入损坏 JSON → 有限重试内收敛或抛明确失败；
       重试次数 ≤ 配置上界（config output_pipeline.max_retries）
    2. 契约非法（如 rating 自由文本）被业务校验拒绝
    3. one_liner 存在且 ≤30 字（结构断言，AC-005）
    4. disclaimer 非空且四种响应形态都有（AC-010）
    5. 建议条数 3-5 条、无空话黑名单词单独成条（结构断言，AC-006；
       具体性/温暖度是人工项，不在本任务）
    6. 测试路径经 cassette 固定模型行为，离线可重复、零真实 API 调用

只通过唯一接缝 execute_query 断言结构化响应契约（spec Testing Decisions），
管线运行时本体（output_pipeline.run_pipeline）是统一运行时，直接以
注入 fake 断言其重试/校验/失败语义。
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from safepass import config_loader, contracts, routing
from safepass.llm_client import ChatResponse, reset_cassette_cursor, chat_with_cassette
from safepass.output_pipeline import (
    BusinessValidationError,
    OutputPipelineError,
    make_suggestions_validator,
    run_pipeline,
    validate_contract,
    validate_legal_rating,
    validate_non_empty_disclaimer,
    validate_one_liner,
)
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE = REPO_ROOT / "tests" / "cassettes" / "fc_routing.json"
# issue 09 / T7 起，接缝路径在注入客户端时消费 2 次 LLM 调用（路由 + 三维提取），
# 与 fc_routing.json（纯路由 5 条、按序消费）互斥——接缝用例改走专用 cassette。
CASSETTE_SEAM = REPO_ROOT / "tests" / "cassettes" / "fc_routing_seam.json"


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


class _AlwaysCorruptLLM:
    """无论多少次调用都返回不可解析内容的 fake（重试上界探针）。"""

    def __init__(self, content: str = "这不是 JSON，也不是对象"):
        self._content = content
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(content=self._content, model="fake")


class _LooseSafetyContract(BaseModel):
    """故意在结构层放开 rating（str）的契约：rating 自由文本只能被业务校验拦住。"""

    type: str = "safety"
    area: str
    precinct: int
    rating: str  # 结构层不拦自由文本——业务校验必须拦（issue 06 勾选 2）
    sample_size: int
    one_liner: str
    sources: list[str]
    time_range: str
    disclaimer: str


def _safety_payload(rating: str = "yellow") -> dict[str, Any]:
    return {
        "type": "safety",
        "area": "上东区",
        "precinct": 19,
        "rating": rating,
        "sample_size": 120,
        "one_liner": "上东区：🟡 需注意",
        "extracted": {"area": None, "crowd": None, "time": None},  # AC-002（issue 09）
        "profile_notice": "画像仅在本次会话生效，关闭页面即删除",  # AC-023（issue 09）
        "sources": ["模拟数据"],
        "time_range": "2025-07~2026-06",
        "disclaimer": "本分析仅供参考，不替代专业安保建议。",
    }


class _CassetteClient:
    """把调用转发到 chat_with_cassette 的客户端：录制一次，之后离线零调用回放。"""

    def __init__(self, inner, path: Path):
        self._inner = inner
        self._path = path
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return chat_with_cassette(self._inner, self._path, messages, model=model, **kwargs)


class _FailIfCalled:
    """回放路径的底座客户端：被调用即失败（证明 cassette 真的零真实/零 fake 调用）。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("cassette 回放不应触发任何底层客户端调用")


# ---------------------------------------------------------------------------
# 1. 输出控制管线集：损坏 JSON → 有限重试内收敛或抛明确失败；重试 ≤ 配置上界
# ---------------------------------------------------------------------------


def test_corrupt_json_then_valid_converges_within_retry_bound():
    """前两次输出损坏（非 JSON / 截断对象），第三次合法 → 管线内收敛，不抛异常。"""
    cfg = config_loader.load_config()
    payload = json.dumps(_safety_payload(), ensure_ascii=False)
    fake = _ScriptedFakeLLM(script=["这根本不是 JSON", '{"area": "上东区", broken', payload])

    result = run_pipeline(
        fake,
        [{"role": "user", "content": "上东区安全吗"}],
        _LooseSafetyContract,
        cfg,
    )
    assert isinstance(result, _LooseSafetyContract)
    assert result.rating == "yellow"
    assert fake.calls == 3, "第三次尝试收敛：调用次数应恰好等于收敛所需次数"
    assert fake.calls <= cfg.max_retries + 1, "调用次数 ≤ 初始尝试 + 配置重试上界"


def test_fenced_json_with_prose_is_repaired_on_first_attempt():
    """markdown 围栏 + 前后散文 → 解析/修复段直接还原对象，一次调用即收敛。"""
    cfg = config_loader.load_config()
    payload = json.dumps(_safety_payload(rating="green"), ensure_ascii=False)
    fenced = f"好的，以下是结果：\n```json\n{payload}\n```\n希望有帮助！"
    fake = _ScriptedFakeLLM(script=[fenced])

    result = run_pipeline(
        fake,
        [{"role": "user", "content": "上东区安全吗"}],
        _LooseSafetyContract,
        cfg,
    )
    assert result.rating == "green"
    assert fake.calls == 1, "可修复输出不应浪费重试"


def test_all_corrupt_raises_explicit_failure_within_retry_bound():
    """输出永远损坏 → 抛 OutputPipelineError（明确失败），且调用次数 ≤ 配置上界。"""
    cfg = config_loader.load_config()
    fake = _AlwaysCorruptLLM()

    with pytest.raises(OutputPipelineError) as excinfo:
        run_pipeline(
            fake,
            [{"role": "user", "content": "上东区安全吗"}],
            _LooseSafetyContract,
            cfg,
        )
    assert "契约" in str(excinfo.value) or "_LooseSafetyContract" in str(excinfo.value)
    assert fake.calls == cfg.max_retries + 1, (
        f"尝试次数 = 1 + max_retries({cfg.max_retries})，不得超出配置上界"
    )


def test_retry_feedback_is_fed_back_into_next_attempt():
    """参考 helper_planning 模式：失败原因要回灌进下一轮消息，而不是盲目重试。"""
    cfg = config_loader.load_config()
    payload = json.dumps(_safety_payload(), ensure_ascii=False)
    fake = _ScriptedFakeLLM(script=["不是 JSON", payload])

    run_pipeline(
        fake,
        [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
        _LooseSafetyContract,
        cfg,
    )
    assert len(fake.seen_messages) == 2
    first, second = fake.seen_messages
    assert len(second) == len(first) + 1, "第二次尝试应带上失败反馈消息"
    feedback = second[-1]
    assert feedback["role"] == "user"
    assert "解析" in feedback["content"] or "校验" in feedback["content"]


def test_first_attempt_success_makes_single_call():
    cfg = config_loader.load_config()
    fake = _ScriptedFakeLLM(script=[json.dumps(_safety_payload(), ensure_ascii=False)])
    run_pipeline(fake, [{"role": "user", "content": "q"}], _LooseSafetyContract, cfg)
    assert fake.calls == 1


# ---------------------------------------------------------------------------
# 2. 契约非法（rating 自由文本）被业务校验拒绝
# ---------------------------------------------------------------------------


def test_free_text_rating_rejected_by_business_validation():
    """rating="相当危险" 结构上是 str 拦不住 → 业务校验必须拒绝 →
    有限重试后抛明确失败，绝不把自由文本评级放进契约。"""
    cfg = config_loader.load_config()
    bad = json.dumps(_safety_payload(rating="相当危险"), ensure_ascii=False)
    fake = _ScriptedFakeLLM(script=[bad] * (cfg.max_retries + 1))

    with pytest.raises(OutputPipelineError) as excinfo:
        run_pipeline(
            fake,
            [{"role": "user", "content": "q"}],
            _LooseSafetyContract,
            cfg,
            validators=[validate_legal_rating],
        )
    assert "相当危险" in str(excinfo.value), "失败信息应点明被拒的自由文本"
    assert fake.calls == cfg.max_retries + 1


def test_structure_validation_failure_also_retries_then_fails_explicitly():
    """缺必填字段（结构层非法）→ 同样走有限重试 → 明确失败。"""
    cfg = config_loader.load_config()
    incomplete = _safety_payload()
    del incomplete["disclaimer"]
    fake = _ScriptedFakeLLM(script=[json.dumps(incomplete, ensure_ascii=False)] * (cfg.max_retries + 1))
    with pytest.raises(OutputPipelineError):
        run_pipeline(fake, [{"role": "user", "content": "q"}], _LooseSafetyContract, cfg)
    assert fake.calls == cfg.max_retries + 1


def test_validate_legal_rating_accepts_enum_values():
    cfg = config_loader.load_config()
    model = _LooseSafetyContract(**_safety_payload(rating="red"))
    validate_contract(model, [validate_legal_rating])  # 不抛即通过
    with pytest.raises(BusinessValidationError):
        validate_contract(
            _LooseSafetyContract(**_safety_payload(rating="security score 7")),
            [validate_legal_rating],
        )


# ---------------------------------------------------------------------------
# 3. 契约四形态：评级枚举、disclaimer 齐备、one_liner/建议结构规则
# ---------------------------------------------------------------------------


def test_rating_field_is_enum_not_free_text_at_contract_level():
    """spec D3：评级字段是枚举。契约层直接拒绝自由文本（双保险）。"""
    payload = _safety_payload(rating="相当危险")
    with pytest.raises(ValidationError):
        contracts.SafetyQueryResult(**{**payload, "charts": None})
    for legal in contracts.LEGAL_RATINGS:
        model = contracts.SafetyQueryResult(**{**_safety_payload(rating=legal), "charts": None})
        assert model.rating == legal


def test_legal_ratings_anchor_matches_config_forced_tier():
    """配置强制档（⚪）的 rating 取值必须是合法枚举（评级可复算集同源配置）。"""
    cfg = config_loader.load_config()
    forced = [t.rating for t in cfg.sample_size_tiers if t.rating is not None]
    assert forced, "配置必须存在强制评级档"
    for rating in forced:
        assert rating in contracts.LEGAL_RATINGS


@pytest.mark.parametrize(
    "build",
    [
        lambda: contracts.SafetyQueryResult(
            area="上东区", precinct=19, rating="yellow", sample_size=120,
            one_liner="上东区：🟡 需注意",
            extracted={"area": None, "crowd": None, "time": None},
            profile_notice="画像仅在本次会话生效，关闭页面即删除",
            sources=["模拟数据"],
            time_range="2025-07~2026-06", charts=None, disclaimer="d",
        ),
        lambda: contracts.DegradedResult(
            degraded_capability="path", message="m",
            reselection_invitation="r", disclaimer="d",
        ),
        lambda: contracts.ComparisonResult(disclaimer="d"),
        lambda: contracts.EmergencyResult(
            call_911_prompt="p", chinese_interpreter_phrase="c",
            info_checklist=["i"], comfort_message="m", disclaimer="d",
        ),
        lambda: contracts.GuardrailResult(
            guardrail_kind="bias_refusal", message="m",
            alternatives=["a", "b", "c"], disclaimer="d",
        ),
    ],
    ids=["safety", "degraded", "comparison", "emergency", "guardrail"],
)
def test_all_five_response_forms_require_non_empty_disclaimer(build):
    """AC-010：disclaimer 是全部响应形态（spec D3 四种 + issue 09 guardrail）共有的必填横切字段。"""
    model = build()
    assert model.disclaimer == "d"
    # model_copy 不做校验，重建实例才是结构层断言
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(exclude={"type"}), "disclaimer": ""})


def test_emergency_result_is_marked_emergency():
    """紧急形态契约自带 is_emergency=true；核心话术字段结构层必填（T5 装配填充）。"""
    result = contracts.EmergencyResult(
        call_911_prompt="p", chinese_interpreter_phrase="c",
        info_checklist=["i"], comfort_message="m", disclaimer="d",
    )
    assert result.type == "emergency"
    assert result.is_emergency is True


def test_one_liner_rule_enforces_30_char_cap():
    cfg = config_loader.load_config()
    base = {**_safety_payload(), "charts": None}
    ok = contracts.SafetyQueryResult(**base)
    validate_contract(ok, [validate_one_liner])

    long_text = "这是一条故意写得很长、用来触发结构断言的总结文案，字数已确认超过三十"
    assert len(long_text) > 30
    # 契约层：max_length=30 直接拒（spec D3 把 ≤30 字列为契约属性）
    with pytest.raises(ValidationError):
        contracts.SafetyQueryResult(**{**base, "one_liner": long_text})
    # 业务校验层：宽松契约（结构不拦长度）由 validate_one_liner 兜底
    loose = _LooseSafetyContract(**{**_safety_payload(), "one_liner": long_text})
    with pytest.raises(BusinessValidationError):
        validate_contract(loose, [validate_one_liner])


def test_suggestions_rule_enforces_count_and_empty_talk_blacklist():
    """AC-006 结构：3-5 条；空话黑名单词（配置）不得单独成条。"""
    cfg = config_loader.load_config()
    assert cfg.suggestions.empty_talk_blacklist, "配置必须给出空话黑名单"
    validator = make_suggestions_validator(cfg)
    base = {**_safety_payload(), "charts": None}

    good = contracts.SafetyQueryResult(
        **{**base, "suggestions": list(cfg.suggestions.safety_general)}
    )
    validate_contract(good, [validator])
    assert 3 <= len(good.suggestions) <= 5

    too_few = contracts.SafetyQueryResult(**{**base, "suggestions": ["a", "b"]})
    with pytest.raises(BusinessValidationError):
        validate_contract(too_few, [validator])

    too_many = contracts.SafetyQueryResult(**{**base, "suggestions": ["x"] * 6})
    with pytest.raises(BusinessValidationError):
        validate_contract(too_many, [validator])

    empty_talk = contracts.SafetyQueryResult(
        **{**base, "suggestions": ["走主干道", cfg.suggestions.empty_talk_blacklist[0], "结伴出行"]}
    )
    with pytest.raises(BusinessValidationError):
        validate_contract(empty_talk, [validator])

    blank_item = contracts.SafetyQueryResult(**{**base, "suggestions": ["  ", "a", "b"]})
    with pytest.raises(BusinessValidationError):
        validate_contract(blank_item, [validator])


def test_disclaimer_validator_rejects_empty():
    with pytest.raises(BusinessValidationError):
        validate_contract(
            contracts.DegradedResult(
                degraded_capability="trend", message="m",
                reselection_invitation="r", disclaimer="  ",
            ),
            [validate_non_empty_disclaimer],
        )


# ---------------------------------------------------------------------------
# 4. 结构断言经唯一接缝：one_liner ≤30、建议 3-5 条、横切字段齐备
# ---------------------------------------------------------------------------


def test_safety_result_one_liner_within_30_chars_via_seam():
    result = execute_query("上东区晚上安全吗？")
    assert result.type == "safety"
    assert result.one_liner, "AC-005：一句话总结必须存在"
    assert len(result.one_liner) <= 30, f"one_liner 超过 30 字：{result.one_liner}"


def test_safety_result_suggestions_shape_via_seam():
    result = execute_query("上东区晚上安全吗？")
    assert result.type == "safety"
    assert 3 <= len(result.suggestions) <= 5, "AC-006：建议必须 3-5 条"
    cfg = config_loader.load_config()
    blacklist = set(cfg.suggestions.empty_talk_blacklist)
    for suggestion in result.suggestions:
        assert suggestion.strip(), "建议不得为空条目"
        assert suggestion.strip() not in blacklist, f"空话黑名单词单独成条：{suggestion!r}"


def test_safety_result_cross_cutting_fields_present():
    result = execute_query("上东区晚上安全吗？")
    assert result.type == "safety"
    assert result.disclaimer.strip(), "AC-010：免责声明每处存在"
    assert result.sources, "AC-008：来源标注非空"
    assert result.sample_size > 0


def test_degraded_result_suggestions_shape_via_seam():
    result = execute_query("哥大附近安全吗？")
    assert result.type == "degraded"
    assert 3 <= len(result.general_suggestions) <= 5
    cfg = config_loader.load_config()
    blacklist = set(cfg.suggestions.empty_talk_blacklist)
    for suggestion in result.general_suggestions:
        assert suggestion.strip() not in blacklist


# ---------------------------------------------------------------------------
# 5. cassette 固定模型行为：离线可重复、零真实 API 调用
# ---------------------------------------------------------------------------


def test_fc_routing_replay_offline_zero_calls():
    """五条路由判定（含四类工具 + 降级意图细分）全部由
    tests/cassettes/fc_routing.json 固定，回放时底层客户端调用计数 = 0。"""
    cfg = config_loader.load_config()
    inner = _FailIfCalled()
    client = _CassetteClient(inner, CASSETTE)
    reset_cassette_cursor(CASSETTE)

    cases = [
        ("上东区晚上安全吗？", routing.ROUTE_AREA_SAFETY, None),
        ("上东区和法拉盛哪个更安全？", routing.ROUTE_AREA_COMPARISON, None),
        ("我家楼下有个陌生人一直跟着我，我很害怕", routing.ROUTE_EMERGENCY, None),
        ("那女生晚上呢？", routing.ROUTE_FOLLOW_UP, None),
        ("两地之间如何通行最安全？", routing.ROUTE_DEGRADED, "path"),
    ]
    for query, expected_route, expected_capability in cases:
        decision = routing.route_query(query, client, cfg)
        assert decision.route == expected_route, f"{query!r} 应路由到 {expected_route}（cassette 固定）"
        assert decision.degraded_capability == expected_capability
    assert inner.calls == 0, "cassette 回放必须零底层调用（离线可重复）"


def test_execute_query_consumes_cassette_fixed_routing():
    """唯一接缝路径上，模型行为同样由 cassette 固定：LLM 路由出安全查询契约。

    T7 起接缝在注入客户端时消费 2 次 LLM 调用（FC 路由 + 三维提取），
    本用例使用专用 cassette（fc_routing_seam.json，2 条交互顺序消费）。
    """
    inner = _FailIfCalled()
    client = _CassetteClient(inner, CASSETTE_SEAM)
    reset_cassette_cursor(CASSETTE_SEAM)

    result = execute_query("上东区晚上安全吗？", llm_client=client)

    assert inner.calls == 0
    assert client.calls == 2, "接缝 LLM 路径 = 路由 1 次 + 三维提取 1 次（T7）"
    assert result.type == "safety"
    assert result.rating in contracts.LEGAL_RATINGS
    assert result.extracted.time is not None, "三维提取经 cassette 固定并透出契约（AC-002）"


def test_seam_cassette_asset_committed_and_wellformed():
    """接缝专用 cassette 资产完整性：2 条交互（路由 → 三维提取）。"""
    assert CASSETTE_SEAM.exists(), "缺少 tests/cassettes/fc_routing_seam.json（需录制后提交）"
    data = json.loads(CASSETTE_SEAM.read_text(encoding="utf-8"))
    interactions = data["interactions"]
    assert len(interactions) == 2, "fc_routing_seam.json 固定 2 条交互（路由 + 三维提取）"
    assert all(e["fingerprint"] for e in interactions)
    route_payload = json.loads(interactions[0]["response"]["content"])
    assert route_payload["route"] == "area_safety_query"
    extraction_payload = json.loads(interactions[1]["response"]["content"])
    assert "area" in extraction_payload and "crowd" in extraction_payload


def test_cassette_asset_committed_and_wellformed():
    """cassette 是版本化测试资产：存在、交互数与指纹齐全。"""
    assert CASSETTE.exists(), "缺少 tests/cassettes/fc_routing.json（需录制后提交）"
    data = json.loads(CASSETTE.read_text(encoding="utf-8"))
    interactions = data["interactions"]
    assert len(interactions) == 5, "fc_routing.json 应固定 5 条路由交互"
    for entry in interactions:
        assert entry["fingerprint"]
        assert entry["response"]["content"]


def test_routing_exhausts_cassette_then_fails_explicitly():
    """cassette 耗尽后再消费 → CassetteError 明确失败（不静默、不回退真实 API）。"""
    from safepass.llm_client import CassetteError

    cfg = config_loader.load_config()
    inner = _FailIfCalled()
    client = _CassetteClient(inner, CASSETTE)
    reset_cassette_cursor(CASSETTE)
    queries = [
        "上东区晚上安全吗？",
        "上东区和法拉盛哪个更安全？",
        "我家楼下有个陌生人一直跟着我，我很害怕",
        "那女生晚上呢？",
        "两地之间如何通行最安全？",
    ]
    for query in queries:
        routing.route_query(query, client, cfg)
    with pytest.raises(CassetteError):
        routing.route_query("上东区晚上安全吗？", client, cfg)


# ---------------------------------------------------------------------------
# 6. 性能标记：正常查询端到端 P95 < 8s（留 20% 余量 → 6.4s；UX-001）
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_query_latency_p95_within_budget():
    cfg = config_loader.load_config()
    durations: list[float] = []
    for _ in range(7):
        fake = _ScriptedFakeLLM(
            script=[
                json.dumps({"route": "area_safety_query"}),
                json.dumps({"area": "上东区", "crowd": None, "time": "晚上"}),
            ]
        )
        start = time.perf_counter()
        execute_query("上东区晚上安全吗？", llm_client=fake)
        durations.append(time.perf_counter() - start)
    durations.sort()
    p95 = durations[int(math.ceil(0.95 * len(durations))) - 1]
    assert p95 < 8 * 0.8, f"查询 P95 {p95:.2f}s 超出 UX-001 预算（8s × 0.8 余量）"
