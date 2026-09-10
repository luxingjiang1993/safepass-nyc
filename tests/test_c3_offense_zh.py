"""票 05 / C3：Top5 与建议共用配置里的中文罪名；未知类型外显「其他」，计数保留。

接缝：唯一接缝 execute_query。
    图表 label_zh 与建议 Skill 数据包用同一套配置映射；
    mock fixture 已出现的类型必须有中文名；
    配置没有的类型外显 unknown_offense_label，计数不丢。
本票不跑 L2。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from safepass import addressing, config_loader, contracts, data_agent
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query
from frontend import render

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"

# mock fixture 类型 → 产品中文名（独立字面量，不从 loader 反推）
FIXTURE_OFFENSE_ZH = {
    "GRAND LARCENY": "重大盗窃",
    "ROBBERY": "抢劫",
    "BURGLARY": "入室盗窃",
    "FELONY ASSAULT": "重伤害",
    "PETIT LARCENY": "轻微盗窃",
    "HARRASSMENT 2": "骚扰",
    "CRIMINAL MISCHIEF": "刑事毁坏",
    "MISDEMEANOR ASSAULT": "轻伤害",
}

_ROUTE_OUT = json.dumps({"route": "area_safety_query"}, ensure_ascii=False)
_EXTRACTION_OUT = json.dumps(
    {"area": "上东区", "crowd": None, "time": None}, ensure_ascii=False
)
_SKILL_OUT = json.dumps(
    {
        "suggestions": [
            "夜间出行优先选择照明好、人流多的主干道",
            "随身包放在身前视线范围内",
            "不要把英文法律名当成已核对的罪名",
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


def _fixture_offense_types() -> set[str]:
    with NYPD_CSV.open(newline="", encoding="utf-8") as f:
        return {row["offense_type"] for row in csv.DictReader(f)}


def test_fixture_offense_types_have_config_zh_names():
    """mock 数据集里出现过的类型，配置里都有中文名。"""
    cfg = config_loader.load_config()
    names = cfg.one_liner.type_names
    for code in _fixture_offense_types():
        assert code in names, f"fixture 类型 {code!r} 缺少中文映射"
        assert names[code] == FIXTURE_OFFENSE_ZH[code]
    assert cfg.one_liner.unknown_offense_label == "其他"


def test_charts_and_skill_share_fixture_zh_labels():
    """覆盖内查询：Top5 与建议数据包用同一套中文名，不是英文法律名。"""
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT, _SKILL_OUT])
    result = execute_query("上东区安全吗？", llm_client=fake)
    assert isinstance(result, contracts.SafetyQueryResult)
    assert result.charts is not None
    labels = []
    for item in result.charts.top5_types:
        assert item.offense_type in FIXTURE_OFFENSE_ZH
        expected = FIXTURE_OFFENSE_ZH[item.offense_type]
        assert item.label_zh == expected
        assert item.label_zh != item.offense_type
        labels.append(item.label_zh)
    skill_text = "\n".join(m["content"] for call in fake.seen_messages for m in call)
    for label in labels:
        assert label in skill_text
        assert f"{label} " in skill_text or f"{label}\n" in skill_text
    for item in result.charts.top5_types:
        assert item.offense_type not in skill_text
    html = render.render_result(result, config_loader.load_config())
    for label in labels:
        assert label in html
    for item in result.charts.top5_types:
        assert item.offense_type not in html


def _write_unmapped_csv(path: Path, precinct: int, rows_types: list[str]) -> Path:
    fieldnames = ["complaint_id", "precinct", "borough", "offense_level", "offense_type",
                  "occurred_at", "source"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for i, offense in enumerate(rows_types, 1):
            writer.writerow({
                "complaint_id": f"UNK-{i:03d}",
                "precinct": precinct,
                "borough": "X",
                "offense_level": "X",
                "offense_type": offense,
                "occurred_at": "2026-01-15T10:00:00",
                "source": "MOCK_SYNTHETIC",
            })
    return path


def test_unmapped_offense_shows_other_and_keeps_count(tmp_path, monkeypatch):
    """配置没有的类型外显「其他」，两条未知类型各自保留计数，不合并、不吞掉。"""
    cfg = config_loader.load_config()
    precinct = addressing.resolve_areas("上东区", cfg)[0].precincts[0]
    other = cfg.one_liner.unknown_offense_label
    csv_path = _write_unmapped_csv(
        tmp_path / "unmapped.csv",
        precinct,
        ["AAA_UNKNOWN"] * 12 + ["BBB_UNKNOWN"] * 11,
    )
    monkeypatch.setenv(data_agent.DATASET_PATH_ENV, str(csv_path))
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT, _SKILL_OUT])
    result = execute_query("上东区安全吗？", llm_client=fake)
    assert isinstance(result, contracts.SafetyQueryResult)
    assert result.charts is not None
    pairs = [(t.offense_type, t.label_zh, t.count) for t in result.charts.top5_types]
    assert ("AAA_UNKNOWN", other, 12) in pairs
    assert ("BBB_UNKNOWN", other, 11) in pairs
    html = render.render_result(result, cfg)
    assert other in html
    assert f">{12}<" in html
    assert f">{11}<" in html
    assert "AAA_UNKNOWN" not in html
    assert "BBB_UNKNOWN" not in html
    skill_text = "\n".join(m["content"] for call in fake.seen_messages for m in call)
    assert other in skill_text
    assert "AAA_UNKNOWN" not in skill_text
    assert "BBB_UNKNOWN" not in skill_text
