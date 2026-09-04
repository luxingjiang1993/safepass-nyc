"""issue 07 / RALPH T5 验收测试：紧急触发集。

对应 .scratch/safepass-nyc-mvp/issues/07-emergency-detection-static-assembly.md 五条勾选：
    1. 关键词直录 + 改写句合计触发率 > 95%（改写句层用 cassette 回放验证）
    2. 静态分支 LLM 调用计数 = 0（第一层关键词命中后路由 LLM 不可达）
    3. EmergencyResult 组装 < 2s（perf 标记；P95 留 20% 余量 → 1.6s）
    4. 清单字段与警区静态表逐字段一致；无区域查询历史 → 通用清单且无"最近"类定位词
    5. 字段断言：911 按钮文案、中文报警用语、信息准备清单、安抚话术、311/社区电话非空

只通过唯一接缝 execute_query 断言结构化响应契约（spec Testing Decisions），
不断言管线内部交互、不 mock 管线内部。LLM 行为经 cassette 固定
（tests/cassettes/emergency_fc.json），离线可重复、零真实 API 调用。
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from safepass import config_loader, emergency
from safepass.llm_client import ChatResponse, chat_with_cassette, reset_cassette_cursor
from safepass.pipeline import execute_query

_all_text = emergency._all_text  # 复用装配层的文本收集器（与守卫扫描同源）

REPO_ROOT = Path(__file__).resolve().parent.parent
SAFE_PLACES_JSON = REPO_ROOT / "fixtures" / "safe_places" / "precinct_safe_places.json"
CASSETTE = REPO_ROOT / "tests" / "cassettes" / "emergency_fc.json"

# 第一层关键词直录用例：查询文本直接包含静态表关键词（优先于一切 LLM 调用）
KEYWORD_DIRECT_QUERIES = [
    "救命，有人持刀！",
    "我在法拉盛被跟踪了",
    "有人跟着我，我很害怕",
    "被抢劫了怎么办",
    "我家楼下有人打起来了",
    "紧急求助！出事了",
    "我受伤了，流了很多血",
    "有人开枪！快报警",
    "我的包被抢了，人还没走远",
    "楼道着火了，全是烟",
    "有人拿刀威胁我",
    "救我，遇袭了",
]

# 第二层改写句用例：不含任何静态表关键词，由 FC 路由 emergency_help 兜底接住
# （顺序 = tests/cassettes/emergency_fc.json 交互顺序）。
REWRITE_QUERIES = [
    "有个陌生男人在地铁口一路跟我回家",
    "我被人堵住威胁要掏钱，现在躲在商店里",
    "刚才有人砸车窗拿走了我的包，我现在手还在抖",
    "我闻到楼道里全是烟，好像哪里烧起来了",
    "深夜回家路上发现身后有同一个影子跟了两条街",
    "有人不停敲我的车门让我开窗，我不认识他",
]

# 无区域查询历史的紧急输入：通用清单 + 禁止出现"最近"类暗示定位的词
NO_AREA_QUERIES = [
    "救命，有人持刀！",
    "有人开枪！快报警",
    "救我，遇袭了",
    "紧急求助！出事了",
    "我在哥大附近被跟踪了",  # 越界区域：同样无按警区清单，回退通用清单
]

CHINESE_INTERPRETER_PHRASE = "I need help. Can I have a Chinese interpreter?"


class _FakeLLM:
    """计数 fake：被调用即返回安全查询路由（第一层命中后它不该被调用）。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(content=json.dumps({"route": "area_safety_query"}), model="fake")


class _CassetteClient:
    """把调用转发到 chat_with_cassette：回放已录制的路由响应，并计数。"""

    def __init__(self, inner, path: Path):
        self._inner = inner
        self._path = path
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return chat_with_cassette(self._inner, self._path, messages, model=model, **kwargs)


class _FailIfCalled:
    """回放路径的底座客户端：被调用即失败（证明 cassette 真的零底层调用）。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("cassette 回放不应触发任何底层客户端调用")


def _load_fixture() -> dict[str, Any]:
    return json.loads(SAFE_PLACES_JSON.read_text(encoding="utf-8"))


class _RoutedFakeLLM:
    """计数 fake：按注入的 route 返回固定 FC 路由 JSON（第二层排序回归用）。"""

    def __init__(self, route: str) -> None:
        self.calls = 0
        self._route = route

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(
            content=json.dumps({"route": self._route}), model="fake"
        )


# ---------------------------------------------------------------------------
# 勾选 1：关键词直录 + 改写句合计触发率 > 95%（改写句层 cassette 回放）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", KEYWORD_DIRECT_QUERIES)
def test_keyword_direct_query_triggers_emergency(query: str):
    """第一层关键词静态表命中 → EmergencyResult，优先于一切 LLM 调用。"""
    result = execute_query(query)
    assert result.type == "emergency"
    assert result.is_emergency is True


def test_rewrite_queries_trigger_emergency_via_cassette():
    """第二层：不含关键词的紧急表述由 FC 路由 emergency_help 兜底接住，
    路由判定后同样静态组装（cassette 固定路由行为，离线可重复）。

    cassette 游标按文件全局顺序消费：单条用例内顺序回放全部改写句
    （同 fc_routing.json 的先例）。"""
    inner = _FailIfCalled()
    client = _CassetteClient(inner, CASSETTE)
    reset_cassette_cursor(CASSETTE)

    for query in REWRITE_QUERIES:
        result = execute_query(query, llm_client=client)
        assert result.type == "emergency", f"改写句未触发紧急分支：{query}"
        assert result.is_emergency is True
    assert client.calls == len(REWRITE_QUERIES), (
        "第二层每条改写句只有一次路由 LLM 调用，路由后不再生成自由文本"
    )
    assert inner.calls == 0, "cassette 回放必须零底层调用（离线可重复）"


def test_combined_trigger_rate_above_95_percent():
    """紧急触发集：关键词直录 + 改写句合计触发率 > 95%（rewrite 层 cassette 回放）。"""
    inner = _FailIfCalled()
    client = _CassetteClient(inner, CASSETTE)
    reset_cassette_cursor(CASSETTE)

    triggered = 0
    total = 0
    for query in KEYWORD_DIRECT_QUERIES:
        total += 1
        if execute_query(query).type == "emergency":
            triggered += 1
    for query in REWRITE_QUERIES:
        total += 1
        if execute_query(query, llm_client=client).type == "emergency":
            triggered += 1
    rate = triggered / total
    assert rate > 0.95, f"合计触发率 {rate:.1%} 未达 >95%（{triggered}/{total}）"
    assert inner.calls == 0


# ---------------------------------------------------------------------------
# 勾选 2：静态分支 LLM 调用计数 = 0
# ---------------------------------------------------------------------------


def test_static_branch_makes_zero_llm_calls():
    """第一层命中即进静态分支：注入计数 fake，LLM 调用计数必须为 0。"""
    fake = _FakeLLM()
    result = execute_query("救命，有人持刀！", llm_client=fake)
    assert result.type == "emergency"
    assert fake.calls == 0, "静态分支优先于一切 LLM 调用，调用计数必须为 0"


def test_layer2_emergency_precedes_d12_for_out_of_coverage_area():
    """排序锁定：不含关键词的紧急改写句提到越界区域（哥大附近→26）时，
    FC 路由 emergency_help 必须优先于 D12 越界降级——紧急响应时间敏感且不
    消费数据集（D12 的"无条件"针对的是误路由的数据查询）。"""
    fake = _RoutedFakeLLM(route="emergency_help")
    result = execute_query(
        "深夜回家路上总觉得身后有脚步声，我不敢回头，现在在哥大附近",
        llm_client=fake,
    )
    assert fake.calls == 1, "第二层只有路由这一次 LLM 调用"
    assert result.type == "emergency", "紧急路由必须优先于 D12 越界降级（时间敏感）"
    fixture = _load_fixture()
    assert [v.name for v in result.venues] == [v["name"] for v in fixture["general"]["venues"]]



# ---------------------------------------------------------------------------
# 勾选 4：清单字段与警区静态表逐字段一致；无历史 → 通用清单且无定位词
# ---------------------------------------------------------------------------


def test_venues_match_precinct_static_table_field_by_field():
    """查询文本解析出覆盖内警区 → 按警区安全场所清单逐字段一致（便利店/医院/警局）。"""
    fixture = _load_fixture()
    expected = fixture["precincts"]["109"]["venues"]

    result = execute_query("我在法拉盛被跟踪了")
    assert result.type == "emergency"
    assert len(result.venues) == len(expected)
    for got_v, exp_v in zip(result.venues, expected):
        for key, value in exp_v.items():
            assert getattr(got_v, key) == value, f"警区清单字段 {key} 与静态表不一致"


def test_general_list_without_area_query_history():
    """无区域查询历史 → 通用清单（911/311 + 五警局地址电话）逐字段一致。"""
    fixture = _load_fixture()
    expected = fixture["general"]["venues"]

    result = execute_query("救命，有人持刀！")
    assert result.type == "emergency"
    assert len(result.venues) == len(expected)
    for got_v, exp_v in zip(result.venues, expected):
        for key, value in exp_v.items():
            assert getattr(got_v, key) == value, f"通用清单字段 {key} 与静态表不一致"


def test_out_of_coverage_area_falls_back_to_general_list():
    """解析出越界警区（26）但静态表无该警区条目 → 回退通用清单，绝不编造。"""
    fixture = _load_fixture()
    result = execute_query("我在哥大附近被跟踪了")
    assert result.type == "emergency"
    assert [v.name for v in result.venues] == [v["name"] for v in fixture["general"]["venues"]]


@pytest.mark.parametrize("query", NO_AREA_QUERIES)
def test_no_proximity_words_without_area_history(query: str):
    """无区域查询历史时不得出现"最近""离你最近"等暗示定位的词。"""
    cfg = config_loader.load_config()
    result = execute_query(query)
    assert result.type == "emergency"
    text = _all_text(result)
    for word in cfg.emergency.proximity_blacklist:
        assert word not in text, f"无历史查询的紧急响应出现定位词「{word}」：{query}"


# ---------------------------------------------------------------------------
# 勾选 5：字段断言（AC-014：911 引导/中文报警用语/信息清单/安抚话术/311 电话）
# ---------------------------------------------------------------------------


def test_emergency_core_fields_non_empty():
    """911 按钮文案、中文报警用语、信息准备清单、安抚话术、311/社区电话均非空。"""
    result = execute_query("救命，有人持刀！")
    assert result.type == "emergency"
    assert "911" in result.call_911_prompt, "911 按钮文案必须引导拨打 911"
    assert result.chinese_interpreter_phrase == CHINESE_INTERPRETER_PHRASE
    assert len(result.info_checklist) == 4, "报警信息准备清单：位置/发生了什么/救护车/嫌疑人特征"
    checklist_text = "\n".join(result.info_checklist)
    for theme in ("位置", "发生了什么", "救护车", "嫌疑人"):
        assert theme in checklist_text, f"信息准备清单缺少主题：{theme}"
    assert result.comfort_message.strip(), "安抚话术必须非空"
    assert result.disclaimer.strip(), "免责声明必须每处存在（AC-010）"


def test_non_emergency_contacts_include_311():
    """311 非紧急市政服务电话必须出现在 non_emergency_contacts 中。"""
    result = execute_query("救命，有人持刀！")
    assert result.type == "emergency"
    assert result.non_emergency_contacts, "311/社区协助电话清单不得为空"
    assert any(v.phone == "311" for v in result.non_emergency_contacts), "必须含 311 电话"


def test_emergency_provenance_is_static_table():
    """紧急响应用到的数据资产 = 警区安全场所静态表（每个条目自带 source 字段）。"""
    result = execute_query("我在法拉盛被跟踪了")
    assert result.type == "emergency"
    assert result.sources == ["警区安全场所静态表"]
    assert all(v.source for v in result.venues), "每个清单条目的 source 必须非空可追溯"


def test_config_without_emergency_section_fails_explicitly(tmp_path):
    """集中配置缺少 emergency 段 → ConfigError 明确失败（不静默兜底无关键词表）。"""
    data = yaml.safe_load(config_loader.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    del data["emergency"]
    broken = tmp_path / "app.yaml"
    broken.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(config_loader.ConfigError):
        config_loader.load_config(broken)


# ---------------------------------------------------------------------------
# cassette 资产完整性
# ---------------------------------------------------------------------------


def test_cassette_asset_committed_and_wellformed():
    """cassette 是版本化测试资产：存在、交互数与改写句用例一一对应。"""
    assert CASSETTE.exists(), "缺少 tests/cassettes/emergency_fc.json（需录制后提交）"
    data = json.loads(CASSETTE.read_text(encoding="utf-8"))
    interactions = data["interactions"]
    assert len(interactions) == len(REWRITE_QUERIES), "emergency_fc.json 应固定全部改写句路由交互"
    for entry in interactions:
        assert entry["fingerprint"]
        assert entry["response"]["content"]


# ---------------------------------------------------------------------------
# 勾选 3：性能标记——EmergencyResult 组装 P95 < 2s（留 20% 余量 → 1.6s；UX-006）
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_emergency_assembly_latency_p95_within_budget():
    durations: list[float] = []
    for _ in range(20):
        start = time.perf_counter()
        execute_query("救命，有人持刀！")
        durations.append(time.perf_counter() - start)
    durations.sort()
    p95 = durations[int(math.ceil(0.95 * len(durations))) - 1]
    assert p95 < 2 * 0.8, f"紧急组装 P95 {p95:.3f}s 超出 UX-006 预算（2s × 0.8 余量）"
