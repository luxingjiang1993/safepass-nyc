"""L2 金标判定（issue 03 / M1 勾选三）：50 条金标逐条产出三类 judge 判定结果。

回放路径：judge 调用走 cassette（tests/cassettes/l2_judge.json），
全程离线、零真实 API 调用（注入 _FailIfCalled 底层客户端守住这条红线）。
逐条判定结果与录制工件 fixtures/eval/l2_results_v1.json 对账
（同一 cassette 任何机器上回放必须产出同一结果，Karpathy 宪法②）。

运行（独立套件，不进默认基线）：``pytest tests/eval -q``
"""

from __future__ import annotations

import json

import json_repair
import pytest

from safepass import config_loader
from safepass.llm_client import reset_cassette_cursor

import l2_runner  # 同目录共享 runner（pytest rootdir 插入 tests/eval 至 sys.path）

pytestmark = pytest.mark.eval

_CFG = config_loader.load_config()
_CASSETTE = l2_runner.cassette_path(_CFG)
_EXPECTED_INTERACTIONS = 50 * len(l2_runner.JUDGE_ORDER)


class _FailIfCalled:
    """回放守卫：cassette 存在时底层客户端一次都不许被调（零真实 API）。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("cassette 回放不应触发任何底层客户端调用")


def test_l2_cassette_asset_wellformed():
    """cassette 资产完整性：50 条 × 3 判定 = 150 条交互，指纹与评分载荷齐备。"""
    assert _CASSETTE.exists(), (
        f"缺少 {_CASSETTE.name}（一次性录制：python scripts/record_l2_cassette.py，"
        "需真实 DASHSCOPE_API_KEY；回放不需要）"
    )
    data = json.loads(_CASSETTE.read_text(encoding="utf-8"))
    interactions = data["interactions"]
    assert len(interactions) == _EXPECTED_INTERACTIONS, (
        f"L2 cassette 应恰有 {_EXPECTED_INTERACTIONS} 条交互（50 金标 × "
        f"{len(l2_runner.JUDGE_ORDER)} 判定），实际 {len(interactions)}"
    )
    assert all(e["fingerprint"] for e in interactions)
    for e in interactions:
        payload = json_repair.loads(e["response"]["content"])
        assert isinstance(payload, dict), "每条判定响应必须是结构化 JSON"
        assert "reason" in payload and str(payload["reason"]).strip()


def _replay_suite() -> dict:
    inner = _FailIfCalled()
    reset_cassette_cursor(_CASSETTE)
    results = l2_runner.run_l2_suite(judge_client=inner, cfg=_CFG)
    assert inner.calls == 0, "cassette 回放必须零底层调用"
    return results


def test_l2_all_50_entries_judged_offline():
    """50 条金标逐条判定：条目齐、判定齐、分数在契约区间内、指标聚合就位。"""
    results = _replay_suite()
    entries = results["entries"]
    assert len(entries) == 50, f"金标应为 50 条，实际 {len(entries)}"
    golden_ids = [e["id"] for e in l2_runner.load_golden()]
    assert [e["id"] for e in entries] == golden_ids, "判定顺序必须与金标 fixture 一致"

    for entry in entries:
        verdicts = entry["verdicts"]
        assert set(verdicts) == set(l2_runner.JUDGE_ORDER), (
            f"{entry['id']} 判定不全：{set(verdicts)}"
        )
        for key, verdict in verdicts.items():
            assert 0.0 <= verdict["score"] <= 1.0, f"{entry['id']}.{key} 分数越界"
            assert verdict["reason"].strip(), f"{entry['id']}.{key} 缺判定说明"
            assert verdict["prompt_version"] == _CFG.eval.prompt_versions[key]
            assert verdict["judge_model"] == _CFG.eval.judge_model

    metrics = results["metrics"]
    assert metrics["n_entries"] == 50
    for key in ("groundedness_mean", "relevance_mean", "hallucination_rate"):
        assert metrics[key] is not None and 0.0 <= metrics[key] <= 1.0, (
            f"指标 {key} 缺失或越界：{metrics[key]}"
        )


def test_l2_replay_matches_recorded_results_artifact():
    """同一 cassette 任何机器上回放产出同一结果：回放对账录制工件（复现性）。"""
    artifact_path = l2_runner.RESULTS_PATH
    assert artifact_path.exists(), (
        f"缺少 {artifact_path.name}（录制时由 scripts/record_l2_cassette.py 落盘）"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    replayed = _replay_suite()
    assert replayed["entries"] == artifact["entries"], (
        "回放判定与录制工件不一致：提示词/模板/金标已变更但 cassette 未重新录制"
    )
    assert replayed["metrics"] == artifact["metrics"]


def test_l2_world_pinned_to_mock_dataset():
    """审计问题 #1 护栏：L2 世界（outputs 与 evidence 的数据来源）钉死 mock
    快照，与进程 env / config runtime_dataset_path 漂移无关。录制脚本不经
    pytest conftest——放任默认解析会拿到真实数据集，录出的 cassette 与回放
    世界漂移、指纹全失效（票 07 改 city_mean 的事故重演）。"""
    import os

    from safepass import data_agent

    assert l2_runner.MOCK_DATASET_PATH.name == "mock_nypd.csv"
    assert os.environ[data_agent.DATASET_PATH_ENV] == str(l2_runner.MOCK_DATASET_PATH)

    entry = next(e for e in l2_runner.load_golden() if e["expect"]["type"] == "safety")
    evidence = l2_runner.build_evidence(entry, _CFG)["data"]
    # 独立复算：显式从 mock 快照重算，证据包必须逐字段一致（跨世界即红）
    records = data_agent.load_dataset(l2_runner.MOCK_DATASET_PATH)
    stats = data_agent.aggregate_precinct(records, evidence["precinct"])
    rating_cfg = data_agent.rating_config(records, _CFG)
    assert evidence["sample_size"] == stats.sample_size
    assert evidence["city_mean_per_100k"] == rating_cfg.city_mean_per_100k
    assert evidence["time_range"] == data_agent.load_time_range(l2_runner.MOCK_DATASET_PATH)
