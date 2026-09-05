"""真实数据 adapter 测试（issue 05 / M2，spec v2）。

唯一网络边界：Socrata 响应走录制 fixture（tests/fixtures/socrata_response.json，
由 scripts/fetch_nypd.py --record-fixture 一次性真实录制）；本文件全部测试
离线可跑，HTTP 层一律注入 fake。

覆盖（票 05 验收）：
- 三类拒收路径：缺字段 / 时间越界 / 警区不在清单；
- HTTP 注入接缝（分页参数与拼接）；
- 录制 fixture 回放走完整校验管道；
- 入库产物结构（CSV 列 / manifest 来源标注 / rejected 报告）。
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from safepass import config_loader, nypd_adapter
from scripts import fetch_nypd

REPO_ROOT = Path(__file__).resolve().parents[1]

WINDOW_START = datetime(2025, 9, 5)
WINDOW_END = datetime(2026, 9, 5)  # 不含
ALLOWED = frozenset({19, 109, 5, 90, 84})
SOURCE = "SOCRATA_qgea-i56i"

# 合成行（测试内联 fixture，红线例外条款）：字段形状与真实 Socrata 响应一致。
def make_row(**overrides) -> dict:
    row = {
        "cmplnt_num": "TEST-000001",
        "cmplnt_fr_dt": "2026-01-15T00:00:00.000",
        "cmplnt_fr_tm": "22:30:00",
        "addr_pct_cd": "19",
        "ofns_desc": "GRAND LARCENY",
        "law_cat_cd": "FELONY",
        "boro_nm": "MANHATTAN",
    }
    row.update(overrides)
    return row


def validate(rows, **kwargs):
    params = dict(
        window_start=WINDOW_START,
        window_end_exclusive=WINDOW_END,
        allowed_precincts=ALLOWED,
        source=SOURCE,
    )
    params.update(kwargs)
    return nypd_adapter.validate_rows(rows, **params)


# ---------------------------------------------------------------- 配置解析

def test_config_parses_data_source():
    cfg = config_loader.load_config()
    ds = cfg.data_source
    assert ds.nypd_dataset_id == "qgea-i56i"
    assert ds.socrata_base_url.rstrip("/").endswith("resource")
    assert ds.output_dir and ds.recorded_response
    assert ds.request_timeout_seconds > 0
    assert 0 < ds.page_limit <= ds.page_limit_max


def test_config_rejects_bad_page_limit(tmp_path):
    text = (REPO_ROOT / "config" / "app.yaml").read_text(encoding="utf-8")
    bad = text.replace("page_limit: 50000", "page_limit: 50001")
    p = tmp_path / "app.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(config_loader.ConfigError, match="page_limit"):
        config_loader.load_config(p)


# ---------------------------------------------------------------- 三类拒收路径

def test_missing_field_rejected():
    cases = [
        make_row(ofns_desc=""),                    # 空串
        make_row(cmplnt_fr_tm="(null)"),           # Socrata 占位空值
        make_row(boro_nm="x", ofns_desc=None),     # None
        make_row(cmplnt_fr_dt="not-a-date"),       # 日期不可解析
        make_row(cmplnt_fr_tm="25:99:99"),         # 时间不可解析
    ]
    result = validate(cases)
    assert not result.accepted
    assert len(result.rejected) == len(cases)
    assert all(r.reason == nypd_adapter.REJECT_MISSING_FIELD for r in result.rejected)


def test_out_of_window_rejected():
    cases = [
        make_row(cmplnt_num="OLD", cmplnt_fr_dt="2025-09-04T00:00:00.000"),   # 窗首之前
        make_row(cmplnt_num="NEW", cmplnt_fr_dt="2026-09-05T00:00:00.000"),   # 窗尾（不含）
    ]
    result = validate(cases)
    assert not result.accepted
    assert [r.reason for r in result.rejected] == [
        nypd_adapter.REJECT_OUT_OF_WINDOW,
        nypd_adapter.REJECT_OUT_OF_WINDOW,
    ]


def test_precinct_not_allowed_rejected():
    result = validate([make_row(cmplnt_num="OUT", addr_pct_cd="26")])  # 可识别但不在覆盖清单
    assert not result.accepted
    assert [r.reason for r in result.rejected] == [nypd_adapter.REJECT_PRECINCT_NOT_ALLOWED]


def test_unparseable_precinct_is_missing_field():
    """警区号不可解析 = 数据畸形，归缺字段（拒收统计不把它误记为不在清单）。"""
    result = validate([make_row(cmplnt_num="NA", addr_pct_cd="abc")])
    assert [r.reason for r in result.rejected] == [nypd_adapter.REJECT_MISSING_FIELD]


def test_valid_row_accepted_with_derived_fields():
    result = validate([make_row()])
    assert len(result.accepted) == 1
    r = result.accepted[0]
    assert r.complaint_id == "TEST-000001"
    assert r.precinct == 19
    assert r.occurred_at == datetime(2026, 1, 15, 22, 30, 0)  # 日期 + 时间合成
    assert r.offense_type == "GRAND LARCENY"
    assert r.offense_level == "FELONY"
    assert r.borough == "MANHATTAN"
    assert r.source == SOURCE


def test_validation_union_equals_input_no_silent_loss():
    rows = [
        make_row(cmplnt_num="OK"),
        make_row(cmplnt_num="NO-TIME", cmplnt_fr_tm=""),
        make_row(cmplnt_num="OLD", cmplnt_fr_dt="2020-01-01T00:00:00.000"),
        make_row(cmplnt_num="OUT", addr_pct_cd="26"),
    ]
    result = validate(rows)
    assert len(result.accepted) + len(result.rejected) == len(rows)


def test_rejected_row_keeps_raw_for_report():
    result = validate([make_row(cmplnt_num="RAW-KEEP", cmplnt_fr_tm="")])
    assert result.rejected[0].raw["cmplnt_num"] == "RAW-KEEP"
    assert "cmplnt_fr_tm" in result.rejected[0].detail


# ---------------------------------------------------------------- HTTP 注入接缝

def _plan(precincts=(19, 109), page_limit=2):
    return nypd_adapter.FetchPlan(
        dataset_id="qgea-i56i",
        source_url="https://data.cityofnewyork.us/resource/qgea-i56i.json",
        window_start=WINDOW_START,
        window_end_exclusive=WINDOW_END,
        precincts=precincts,
    )


def test_fetch_paginates_and_concatenates():
    calls: list[dict[str, str]] = []

    def fake_get(url: str, params: dict[str, str]) -> list[dict]:
        calls.append(dict(params))
        offset = int(params["$offset"])
        # 每警区 3 行：page_limit=2 → 第 1 页满（继续），第 2 页 1 行（停）。
        batch = [make_row(cmplnt_num=f"{params['$where'][:12]}-{i}") for i in range(3)]
        return batch[offset : offset + 2]

    rows = nypd_adapter.fetch_complaints(fake_get, plan=_plan(), page_limit=2)
    assert len(rows) == 6  # 2 警区 × 3 行
    # 每警区两页：offset 0（满页）→ offset 2（尾页）
    assert [c["$offset"] for c in calls] == ["0", "2", "0", "2"]
    assert all(c["$limit"] == "2" for c in calls)
    assert all("addr_pct_cd" in c["$where"] for c in calls)
    # 窗口与入库校验同为 [start, end) 半开区间（SoQL between 双闭，不采用）
    assert all(">= '2025-09-05T00:00:00'" in c["$where"] for c in calls)
    assert all("< '2026-09-05T00:00:00'" in c["$where"] for c in calls)
    assert [c["$where"].split(" ")[2] for c in calls] == ["'19'", "'19'", "'109'", "'109'"]


def test_fetch_rejects_non_list_response():
    def fake_get(url: str, params: dict[str, str]):
        return {"error": "shape changed"}

    with pytest.raises(ValueError, match="行列表"):
        nypd_adapter.fetch_complaints(fake_get, plan=_plan(precincts=(19,)), page_limit=2)


def test_fetch_rejects_nonpositive_page_limit():
    with pytest.raises(ValueError, match="page_limit"):
        nypd_adapter.fetch_complaints(lambda u, p: [], plan=_plan(precincts=(19,)), page_limit=0)


# ---------------------------------------------------------------- 录制 fixture 回放

@pytest.fixture(scope="module")
def recorded_doc() -> dict:
    path = REPO_ROOT / "tests" / "fixtures" / "socrata_response.json"
    if not path.exists():
        pytest.skip("录制 fixture 缺失（需 scripts/fetch_nypd.py --record-fixture）")
    return json.loads(path.read_text(encoding="utf-8"))


def test_recorded_fixture_replays_through_validation(recorded_doc):
    cfg = config_loader.load_config()
    plan = fetch_nypd.build_plan(
        cfg,
        today=datetime.strptime(recorded_doc["window_end_exclusive"], "%Y-%m-%d").date(),
    )
    result = nypd_adapter.validate_rows(
        recorded_doc["rows"],
        window_start=plan.window_start,
        window_end_exclusive=plan.window_end_exclusive,
        allowed_precincts=cfg.covered_precincts,
        source="SOCRATA_qgea-i56i",
    )
    rows = recorded_doc["rows"]
    assert len(result.accepted) + len(result.rejected) == len(rows) == recorded_doc["row_count"]
    assert len(result.accepted) > 0
    # 接受的记录全部来自 config 覆盖清单（警区唯一事实源在 config）
    assert {r.precinct for r in result.accepted} <= set(cfg.covered_precincts)
    # 时间戳全部落在录制窗口内
    assert all(plan.window_start <= r.occurred_at < plan.window_end_exclusive for r in result.accepted)


# ---------------------------------------------------------------- 入库产物结构

def test_write_output_artifacts(tmp_path):
    rows = [
        make_row(cmplnt_num="OK-1"),
        make_row(cmplnt_num="OK-2", addr_pct_cd="109", cmplnt_fr_tm="07:15:00"),
        make_row(cmplnt_num="BAD-TIME", cmplnt_fr_tm=""),
        make_row(cmplnt_num="BAD-PCT", addr_pct_cd="26"),
    ]
    result = validate(rows)
    plan = _plan(precincts=(19, 109))
    nypd_adapter.write_output(tmp_path, plan=plan, result=result, fetched_count=len(rows))

    with open(tmp_path / "real_nypd.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == list(nypd_adapter.OUTPUT_COLUMNS)
        accepted_rows = list(reader)
    assert [r["complaint_id"] for r in accepted_rows] == ["OK-1", "OK-2"]
    assert accepted_rows[1]["occurred_at"] == "2026-01-15T07:15:00"
    assert all(r["source"] == SOURCE for r in accepted_rows)
    # 诚实护栏：真实数据不编造 population 字段
    assert "population" not in nypd_adapter.OUTPUT_COLUMNS

    with open(tmp_path / "rejected.csv", newline="", encoding="utf-8") as f:
        rejected_rows = list(csv.DictReader(f))
    assert [r["reason"] for r in rejected_rows] == [
        nypd_adapter.REJECT_MISSING_FIELD,
        nypd_adapter.REJECT_PRECINCT_NOT_ALLOWED,
    ]
    assert all(json.loads(r["raw_json"]) for r in rejected_rows)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == "qgea-i56i"
    assert manifest["source_url"].startswith("https://data.cityofnewyork.us/resource/")
    assert manifest["fetched_count"] == 4
    assert manifest["accepted_count"] == 2
    assert manifest["rejected_count"] == 2
    assert manifest["rejection_counts"] == {
        nypd_adapter.REJECT_MISSING_FIELD: 1,
        nypd_adapter.REJECT_PRECINCT_NOT_ALLOWED: 1,
    }
    assert "Socrata" in manifest["provenance"]


def test_script_run_pipeline_offline(tmp_path, recorded_doc, capsys):
    """scripts/fetch_nypd.run_pipeline 回放录制 fixture：离线跑通同一管道并落盘。"""
    cfg = config_loader.load_config()
    today = datetime.strptime(recorded_doc["window_end_exclusive"], "%Y-%m-%d").date()
    plan = fetch_nypd.build_plan(cfg, today=today)
    out = tmp_path / "nypd_real"
    fetch_nypd.run_pipeline(cfg, recorded_doc["rows"], plan, output_dir=out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["accepted_count"] > 0
    assert manifest["accepted_count"] + manifest["rejected_count"] == recorded_doc["row_count"]
    assert (out / "real_nypd.csv").exists()
    assert (out / "rejected.csv").exists()
    assert "入库完成" in capsys.readouterr().out


def test_script_window_is_trailing_12_calendar_months():
    cfg = config_loader.load_config()
    plan = fetch_nypd.build_plan(cfg, today=datetime(2026, 9, 5).date())
    assert plan.window_start == datetime(2025, 9, 5)
    assert plan.window_end_exclusive == datetime(2026, 9, 5)
    # 回推 12 个月遇闰日钳制：2028-02-29 → 2027-02-28（2027 非闰年）
    edge = fetch_nypd.build_plan(cfg, today=datetime(2028, 2, 29).date())
    assert edge.window_start == datetime(2027, 2, 28)
    assert edge.window_end_exclusive == datetime(2028, 2, 29)
