"""票 01 / C2：可解析钟点切四时段桶，灯不变。

接缝：唯一接缝 execute_query。
    无钟点 = 昼夜合计（time_bucket 空、charts 仍是全年 day/night）；
    有钟点 = 对应该桶；该桶低于配置门槛 → unknowns；
    同一地点改钟点不改变安全评级；时段进建议数据定调，不进画像、不进模型请求的画像字段。
本票不跑 L2。
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from safepass import config_loader
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query
from safepass.skills.suggestion import SuggestionPack

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"

RATING_FIELDS = ("rating", "rating_explainable_basis", "confidence_tier", "sample_size")

_ROUTE_OUT = json.dumps({"route": "area_safety_query"}, ensure_ascii=False)
_EXTRACTION_OUT = json.dumps(
    {"area": "上东区", "crowd": None, "time": "晚上10点"}, ensure_ascii=False
)
_SKILL_OUT = json.dumps(
    {
        "suggestions": [
            "夜间出行优先选择照明好、人流多的主干道，避开偏僻小巷",
            "随身包放在身前视线范围内，手机不要边走边外露",
            "本区该时段样本有限时不要把空桶当成安全",
        ],
        "suggestion_grounds": [],
    },
    ensure_ascii=False,
)


class _ScriptedFakeLLM:
    def __init__(self, script: list[str]):
        self._script = list(script)
        self.seen_messages: list[list[dict]] = []

    def chat(self, messages, *, model=None, **kwargs):
        self.seen_messages.append([dict(m) for m in messages])
        return ChatResponse(content=self._script.pop(0), model="fake")


def _rating_view(result) -> dict:
    return {f: getattr(result, f) for f in RATING_FIELDS}


def _hour_in_bucket(hour: int, start: int, end: int) -> bool:
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _csv_bucket_count(precinct: int, label: str) -> int:
    """Host 侧独立计数：读 mock CSV + 配置桶边界，不调用 data_agent 聚合。"""
    cfg = config_loader.load_config()
    bucket = next(b for b in cfg.time_buckets.buckets if b.label == label)
    n = 0
    with NYPD_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row["precinct"]) != precinct:
                continue
            hour = datetime.strptime(row["occurred_at"], "%Y-%m-%dT%H:%M:%S").hour
            if _hour_in_bucket(hour, bucket.start_hour, bucket.end_hour):
                n += 1
    return n


def test_no_clock_hour_keeps_day_night_totals_and_empty_bucket():
    """不问钟点：仍用昼夜合计，不切四桶。"""
    result = execute_query("上东区安全吗？")
    assert result.type == "safety"
    assert result.time_bucket is None
    assert result.charts is not None
    assert result.charts.day_night.day + result.charts.day_night.night == result.sample_size


def test_clock_hour_selects_late_night_bucket_for_10pm():
    """晚上 10 点 = 深夜桶（CONTEXT / 第三刀 worked example）。"""
    result = execute_query("上东区晚上10点安全吗？")
    assert result.type == "safety"
    assert result.time_bucket is not None
    assert result.time_bucket.label == "深夜"
    assert result.time_bucket.count == _csv_bucket_count(result.precinct, "深夜")


def test_evening_without_clock_hour_does_not_cut_bucket():
    """只有「晚上」没有钟点：仍昼夜合计。"""
    result = execute_query("上东区晚上安全吗？")
    assert result.type == "safety"
    assert result.time_bucket is None


def test_different_clock_hours_split_buckets_same_rating():
    """同一地点改钟点：桶可分，灯不变。"""
    dawn = execute_query("上东区早上7点安全吗？")
    late = execute_query("上东区晚上10点安全吗？")
    none = execute_query("上东区安全吗？")
    assert dawn.time_bucket is not None and late.time_bucket is not None
    assert dawn.time_bucket.label == "清晨"
    assert late.time_bucket.label == "深夜"
    assert dawn.time_bucket.label != late.time_bucket.label
    assert dawn.time_bucket != late.time_bucket
    assert _rating_view(dawn) == _rating_view(late) == _rating_view(none)
    assert dawn.charts == late.charts == none.charts


def test_low_bucket_sample_sets_unknowns_without_inventing():
    """该桶低于配置门槛 → unknowns 用配置话术，不编造；灯仍按全年。"""
    cfg = config_loader.load_config()
    result = execute_query("布鲁克林高地晚上10点安全吗？")
    assert result.type == "safety"
    assert result.time_bucket is not None
    assert result.time_bucket.label == "深夜"
    n = _csv_bucket_count(result.precinct, "深夜")
    assert result.time_bucket.count == n
    assert n < cfg.time_buckets.min_sample
    expected = cfg.time_buckets.unknown_message.format(label="深夜", n=n)
    assert expected in result.unknowns
    assert result.rating == "insufficient_data"


def test_time_bucket_enters_skill_pack_not_profile_or_model_profile_fields():
    """时段进建议数据定调；画像字段不进模型请求。"""
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT, _SKILL_OUT])
    profile = {"crowd": ["带娃"], "scene": "接送孩子上学", "time": "经常加班晚归"}
    result = execute_query("上东区晚上10点安全吗？", profile=profile, llm_client=fake)
    assert result.type == "safety"
    assert result.time_bucket is not None
    all_text = "\n".join(m["content"] for call in fake.seen_messages for m in call)
    assert "查询时段" in all_text
    assert "深夜" in all_text
    for marker in ("带娃", "接送孩子上学", "加班晚归"):
        assert marker not in all_text
    assert SuggestionPack.__dataclass_fields__.keys().isdisjoint({"profile", "persona"})
    assert "经常加班晚归" not in (result.extracted.time or "")
