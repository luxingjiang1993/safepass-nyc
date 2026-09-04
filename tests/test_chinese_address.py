"""issue 09 / RALPH T7 验收测试：中文地址识别集（PRD UX-002 / NEG-007 / AC-001 / AC-002）。

对应 .scratch/safepass-nyc-mvp/issues/09-chinese-address-neg-guardrails.md 勾选：
    1. 10 个常见中文地址 10/10：别名映射（含「布鲁克林 Heights」「哥大附近」→26、
       「中城」跨 14/18）逐地址断言解析警区与端到端响应形态
    2. 扩展标注集 > 90%：更多写法/大小写/问法包裹的标注查询，准确率断言
    3. AC-002 三维提取（区域/人群/时间）在契约中可断言：
       无客户端走确定性 fallback（零 LLM）；注入客户端走 LLM 提取层
       （cassette 固定，回放零底层调用）

只通过唯一接缝 execute_query 与 addressing.resolve_areas 断言（spec Testing Decisions）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from safepass import addressing, config_loader, contracts, data_agent, rating_engine
from safepass.llm_client import ChatResponse, reset_cassette_cursor, chat_with_cassette
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_DIR = REPO_ROOT / "tests" / "cassettes"
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"
CASSETTE_EXTRACTION = CASSETTE_DIR / "extraction_ac002.json"

# ---------------------------------------------------------------------------
# 0. 十个常见中文地址（PRD UX-002）：别名 → 期望警区 + 端到端响应形态
#    （越界/跨警区地址的"正确识别" = 解析出真实警区并诚实降级，绝不硬套数据）
# ---------------------------------------------------------------------------

TEN_ADDRESSES = (
    # (查询, 期望警区, 期望形态)
    ("上东区安全吗？", (19,), "safety"),
    ("上东城治安怎么样", (19,), "safety"),
    ("法拉盛安全吗？", (109,), "safety"),
    ("唐人街晚上安全吗？", (5,), "safety"),
    ("华埠安全吗", (5,), "safety"),
    ("威廉斯堡适合独居吗", (90,), "safety"),
    ("布鲁克林高地安全吗？", (84,), "safety"),
    ("布鲁克林 Heights 怎么样", (84,), "safety"),
    ("哥大附近安全吗？", (26,), "degraded"),
    ("中城安全吗？", (14, 18), "degraded"),
)


@pytest.mark.parametrize(
    "query,expected_precincts,expected_type",
    TEN_ADDRESSES,
    ids=[q for q, _, _ in TEN_ADDRESSES],
)
def test_ten_chinese_addresses_recognized(query, expected_precincts, expected_type):
    """UX-002：10/10——解析警区正确，端到端形态正确（覆盖内 safety / 越界诚实降级）。"""
    cfg = config_loader.load_config()
    resolved = addressing.resolve_areas(query, cfg)
    assert _flatten_precincts(resolved) == expected_precincts, (
        f"{query!r} 应解析出警区 {expected_precincts}"
    )

    result = execute_query(query)
    assert result.type == expected_type
    if expected_type == "safety":
        assert result.precinct == expected_precincts[0]
        expected = _expected_rating(expected_precincts[0])
        assert result.rating == expected.rating, "识别正确后评级必须与阈值规则复算一致"
    else:
        # 越界诚实降级：消息点出识别出的真实警区，绝不硬套其他区域数据
        assert result.degraded_capability == contracts.CAPABILITY_OUT_OF_COVERAGE
        for p in expected_precincts:
            assert str(p) in result.message
        assert result.alternative_info is None


def _flatten_precincts(resolved) -> tuple:
    """展开全部命中区域的警区（中城 = (14, 18) 两个都出现）。"""
    return tuple(p for r in resolved for p in r.precincts)


def _expected_rating(precinct: int) -> rating_engine.RatingResult:
    stats = data_agent.aggregate_precinct(data_agent.load_dataset(NYPD_CSV), precinct)
    return rating_engine.rate_precinct(stats, config_loader.load_config())


# ---------------------------------------------------------------------------
# 1. 扩展标注集（NEG-007）：别名表的更多写法与问法包裹，准确率 > 90%
# ---------------------------------------------------------------------------

LABELED_ADDRESSES = (
    # (查询, 期望警区元组；空元组 = 查询中确实没有可识别区域)
    ("上东区安全吗", (19,)),
    ("上东区晚上安全吗", (19,)),
    ("我是女生，上东区适合独居吗", (19,)),
    ("上东城", (19,)),
    ("Upper East Side 安全吗", (19,)),
    ("upper east side 治安", (19,)),
    ("UES 怎么样", (19,)),
    ("法拉盛", (109,)),
    ("法拉盛 Main Street 安全吗", (109,)),
    ("Flushing 安全吗", (109,)),
    ("flushing 晚上", (109,)),
    ("唐人街", (5,)),
    ("唐人街安全吗", (5,)),
    ("华埠", (5,)),
    ("Chinatown 安全吗", (5,)),
    ("chinatown 晚上安全吗", (5,)),
    ("威廉斯堡", (90,)),
    ("威廉斯堡治安怎么样", (90,)),
    ("Williamsburg 安全吗", (90,)),
    ("布鲁克林高地", (84,)),
    ("布鲁克林 Heights", (84,)),
    ("Brooklyn Heights 安全吗", (84,)),
    ("brooklyn heights", (84,)),
    ("哥大附近", (26,)),
    ("哥伦比亚大学附近安全吗", (26,)),
    ("Columbia University 附近", (26,)),
    ("中城", (14, 18)),
    ("Midtown 安全吗", (14, 18)),
    ("midtown 曼哈顿", (14, 18)),
    ("纽约哪里租房便宜", ()),  # 负例：无区域，诚实识别为"查无所获"
)

# NEG-007 达标线（PRD §8.1 KPI）：扩展标注集准确率 > 90%
NEG007_MIN_ACCURACY = 0.9


def test_extended_labeled_set_accuracy_above_90pct():
    cfg = config_loader.load_config()
    failures = []
    for query, expected in LABELED_ADDRESSES:
        got = _flatten_precincts(addressing.resolve_areas(query, cfg))
        if got != expected:
            failures.append(f"{query!r}: 期望 {expected or '无区域'}，实际 {got or '无区域'}")
    accuracy = 1 - len(failures) / len(LABELED_ADDRESSES)
    assert accuracy > NEG007_MIN_ACCURACY, (
        f"扩展标注集准确率 {accuracy:.1%} 未达标（>{NEG007_MIN_ACCURACY:.0%}）:\n"
        + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# 2. AC-002 三维提取：区域 / 人群 / 时间 在契约中断言
# ---------------------------------------------------------------------------

AC002_QUERY = "我是女生，晚上10点从图书馆回家，Upper East Side安全吗？"


def _assert_ac002_contract(result):
    assert result.type == "safety"
    assert result.precinct == 19, "区域维度：Upper East Side → 19 警区"
    assert result.extracted.area == "Upper East Side"
    assert result.extracted.crowd == "女生"
    assert "晚上" in (result.extracted.time or ""), "时间维度：晚上（具体钟点允许 LLM 细化）"
    # 三维提取只作用于个性化表述，永不改变评级（ADR-0001/0002）
    assert result.rating == _expected_rating(19).rating


def test_ac002_three_dimensions_extracted_deterministic_fallback():
    """无 LLM 客户端：三维提取走确定性 fallback（别名表 + 人群/时间标记，零 LLM）。"""
    result = execute_query(AC002_QUERY)
    _assert_ac002_contract(result)


class _FailIfCalled:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("cassette 回放不应触发任何底层客户端调用")


class _CassetteClient:
    """录制一次，之后离线零调用回放（T5/T6 同款先例）。"""

    def __init__(self, inner, path: Path):
        self._inner = inner
        self._path = path
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return chat_with_cassette(self._inner, self._path, messages, model=model, **kwargs)


def test_ac002_three_dimensions_extracted_via_llm_cassette():
    """注入客户端：三维提取经 LLM 层（输出控制管线），cassette 固定行为、零真实调用。"""
    inner = _FailIfCalled()
    reset_cassette_cursor(CASSETTE_EXTRACTION)
    client = _CassetteClient(inner, CASSETTE_EXTRACTION)

    result = execute_query(AC002_QUERY, llm_client=client)

    assert inner.calls == 0, "cassette 回放必须零底层调用"
    assert client.calls == 2, "LLM 路径 = 路由 1 次 + 三维提取 1 次"
    _assert_ac002_contract(result)


def test_extraction_cassette_asset_wellformed():
    """cassette 资产完整性：2 条交互（路由 → 提取），指纹与 JSON 载荷齐备。"""
    assert CASSETTE_EXTRACTION.exists(), f"缺少 {CASSETTE_EXTRACTION.name}（需录制后提交）"
    data = json.loads(CASSETTE_EXTRACTION.read_text(encoding="utf-8"))
    interactions = data["interactions"]
    assert len(interactions) == 2, "AC-002 cassette 固定 2 条交互（路由 + 三维提取）"
    assert all(e["fingerprint"] for e in interactions)
    route_payload = json.loads(interactions[0]["response"]["content"])
    assert route_payload["route"] == "area_safety_query"
    extraction_payload = json.loads(interactions[1]["response"]["content"])
    assert extraction_payload["area"] == "Upper East Side"
    assert extraction_payload["crowd"] == "女生"
    assert "晚上" in (extraction_payload["time"] or "")


# ---------------------------------------------------------------------------
# 3. 别名映射回归：长别名优先 / 哥大附近 → 26 警区（PRD 用户故事 44 越界识别）
# ---------------------------------------------------------------------------


def test_alias_mapping_regressions():
    cfg = config_loader.load_config()
    by_query = {
        "布鲁克林 Heights": (84,),
        "布鲁克林高地": (84,),
        "哥大附近": (26,),
        "哥伦比亚大学附近": (26,),
        "中城": (14, 18),
        "上东区": (19,),
        "上东城": (19,),
        "华埠": (5,),
    }
    for query, expected in by_query.items():
        resolved = addressing.resolve_areas(query, cfg)
        assert _flatten_precincts(resolved) == expected, query
    # 「布鲁克林 Heights」不被短别名「布鲁克林高地」截断（长别名优先）
    resolved = addressing.resolve_areas("布鲁克林 Heights 安全吗", cfg)
    assert resolved[0].area == "布鲁克林 Heights"
    assert resolved[0].canonical_name == "布鲁克林高地"


def test_chinese_address_query_end_to_end_contract():
    """AC-001 端到端：中文地址查询出完整安全契约（评级/样本量/建议/免责声明）。"""
    result = execute_query("上东区晚上安全吗？我是女生")
    assert result.type == "safety"
    assert result.area == "上东区" and result.precinct == 19
    assert result.rating == _expected_rating(19).rating
    assert result.sample_size == data_agent.aggregate_precinct(
        data_agent.load_dataset(NYPD_CSV), 19
    ).sample_size
    assert 3 <= len(result.suggestions) <= 5
    assert result.disclaimer.strip()
    assert result.sources, "来源标注非空（AC-008）"
    assert re.search(r"[一-鿿]", result.one_liner), "中文用户看到中文一句话总结"


# ---------------------------------------------------------------------------
# 4. cassette 录制助手（一次性在线执行；离线回放路径不经过这里）
# ---------------------------------------------------------------------------


class _ScriptedFake:
    """录制用的剧本 fake：按系统提示词区分路由调用与提取调用。"""

    def chat(self, messages, *, model=None, **kwargs):
        system = messages[0]["content"]
        if "路由助手" in system:
            return ChatResponse(
                content=json.dumps({"route": "area_safety_query"}, ensure_ascii=False),
                model="scripted",
            )
        return ChatResponse(
            content=json.dumps(
                {"area": "Upper East Side", "crowd": "女生", "time": "晚上10点"},
                ensure_ascii=False,
            ),
            model="scripted",
        )


def _record_extraction_cassette():
    """一次性录制入口：真实 execute_query 路径 + 剧本 fake → 落盘 cassette。"""
    if CASSETTE_EXTRACTION.exists():
        CASSETTE_EXTRACTION.unlink()
    client = _CassetteClient(_ScriptedFake(), CASSETTE_EXTRACTION)
    result = execute_query(AC002_QUERY, llm_client=client)
    assert result.type == "safety" and result.precinct == 19


if __name__ == "__main__":
    _record_extraction_cassette()
