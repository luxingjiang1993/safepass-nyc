"""L2 金标判定（issue 03 / M1 起；issue 04 / B1 两路径对照咬合 Skill 输出）。

回放路径：judge 与 Skill 调用一律走 cassette（tests/cassettes/），
全程离线、零真实 API 调用（注入 _FailIfCalled 底层客户端守住这条红线）。
逐条判定结果与录制工件 fixtures/eval/l2_results_v1.json 对账
（同一 cassette 任何机器上回放必须产出同一结果，Karpathy 宪法②）。

B1 主指标口径：Skill 覆盖子集（suggestions_source=skill 的条目，⊆ 24 条
eligible new_query 安全查询，覆盖数受 config eval.skill_coverage_min 护栏）；
模板降级路径单独 marker 不计入主 groundedness；
收口条件 = 两路径同台对照主指标 Skill ≥ 模板（本套件机器断言，非散文）。

B2（issue 05）质量维度：actionability/specificity/矛盾率三维确定性实现
（LLM 零参与），同一 Skill 覆盖子集聚合（主路径 + 模板对照同子集），
回归门 = config eval.quality 的 min_*/max_*（本套件断言），收口条件扩三维。

运行（独立套件，不进默认基线）：``python -m pytest tests/eval -m l2 -q``
"""

from __future__ import annotations

import json

import json_repair
import pytest

from safepass import config_loader, contracts
from safepass.llm_client import reset_cassette_cursor

import l2_runner  # 同目录共享 runner（pytest rootdir 插入 tests/eval 至 sys.path）

pytestmark = [pytest.mark.eval, pytest.mark.l2]

_CFG = config_loader.load_config()
_CASSETTE = l2_runner.cassette_path(_CFG)
_CASSETTE_TEMPLATE = l2_runner.template_judge_cassette_path(_CFG)
_CASSETTE_SKILL = l2_runner.skill_cassette_path(_CFG)
_EXPECTED_JUDGE_INTERACTIONS = 50 * len(l2_runner.JUDGE_ORDER)
# 金标 v1.1 派生计数：eligible 子集 = G25–G48（new_query 安全查询）恰 24 条。
# 交互数理论界与子集形状守卫共用此单一取源，防字面量散布漂移。
_ELIGIBLE_N = 24
# Skill 侧 cassette 交互数是录制世界的确定事实（重试按序进 cassette），
# 权威值 = 录制工件 comparison.skill_cassette_interactions（回放对账同源）；
# 理论界 = eligible 条数 ×（提取 1..1+max_retries + 建议 1..1+max_retries）。
_SKILL_INTERACTIONS_LOWER = _ELIGIBLE_N * 2
_SKILL_INTERACTIONS_UPPER = _ELIGIBLE_N * (2 + 2 * _CFG.max_retries)


class _FailIfCalled:
    """回放守卫：cassette 存在时底层客户端一次都不许被调（零真实 API）。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("cassette 回放不应触发任何底层客户端调用")


def _judge_cassette_wellformed(path, label: str) -> None:
    assert path.exists(), (
        f"缺少 {path.name}（一次性录制：python scripts/record_l2_cassette.py，"
        "需真实 DASHSCOPE_API_KEY；回放不需要）"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    interactions = data["interactions"]
    assert len(interactions) == _EXPECTED_JUDGE_INTERACTIONS, (
        f"{label} cassette 应恰有 {_EXPECTED_JUDGE_INTERACTIONS} 条交互（50 金标 × "
        f"{len(l2_runner.JUDGE_ORDER)} 判定），实际 {len(interactions)}"
    )
    assert all(e["fingerprint"] for e in interactions)
    for e in interactions:
        payload = json_repair.loads(e["response"]["content"])
        assert isinstance(payload, dict), "每条判定响应必须是结构化 JSON"
        assert "reason" in payload and str(payload["reason"]).strip()


def test_l2_cassette_assets_wellformed():
    """cassette 资产完整性：两份 judge cassette 各 150 条交互；Skill 侧
    cassette 交互数落在理论界内且与录制工件对账（重试按序进 cassette，
    权威值 = 工件 comparison.skill_cassette_interactions）。"""
    _judge_cassette_wellformed(_CASSETTE, "主路径（Skill）judge")
    _judge_cassette_wellformed(_CASSETTE_TEMPLATE, "对照路径（模板）judge")
    assert _CASSETTE_SKILL.exists(), (
        f"缺少 {_CASSETTE_SKILL.name}（一次性录制：python scripts/record_l2_cassette.py，"
        "需真实 DASHSCOPE_API_KEY；回放不需要）"
    )
    skill_data = json.loads(_CASSETTE_SKILL.read_text(encoding="utf-8"))
    n = len(skill_data["interactions"])
    assert _SKILL_INTERACTIONS_LOWER <= n <= _SKILL_INTERACTIONS_UPPER, (
        f"Skill 侧 cassette {n} 条交互超出理论界 "
        f"[{_SKILL_INTERACTIONS_LOWER}, {_SKILL_INTERACTIONS_UPPER}]"
    )
    artifact = json.loads(l2_runner.RESULTS_PATH.read_text(encoding="utf-8"))
    assert n == artifact["comparison"]["skill_cassette_interactions"], (
        f"Skill 侧 cassette {n} 条与录制工件 "
        f"{artifact['comparison']['skill_cassette_interactions']} 不符（漂移须重录）"
    )


def _replay_suite() -> dict:
    inner = _FailIfCalled()
    reset_cassette_cursor(_CASSETTE)
    reset_cassette_cursor(_CASSETTE_TEMPLATE)
    reset_cassette_cursor(_CASSETTE_SKILL)
    results = l2_runner.run_l2_suite(judge_client=inner, cfg=_CFG)
    assert inner.calls == 0, "cassette 回放必须零底层调用"
    return results


def test_l2_all_50_entries_judged_offline_both_paths():
    """两路径各 50 条金标逐条判定：条目齐、判定齐、分数在契约区间内。"""
    results = _replay_suite()
    golden_ids = [e["id"] for e in l2_runner.load_golden()]
    for label, entries in (
        ("主路径（Skill）", results["entries"]),
        ("对照路径（模板）", results["template_path"]["entries"]),
    ):
        assert len(entries) == 50, f"{label} 应为 50 条，实际 {len(entries)}"
        assert [e["id"] for e in entries] == golden_ids, (
            f"{label} 判定顺序必须与金标 fixture 一致"
        )
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

    for label, metrics in (
        ("主指标", results["metrics"]),
        ("全量（Skill 路径）", results["metrics_all_entries"]),
        ("模板降级 marker", results["metrics_template_fallback"]),
        ("模板对照（子集）", results["template_path"]["metrics"]),
    ):
        for key in ("groundedness_mean", "relevance_mean", "hallucination_rate"):
            assert metrics[key] is not None and 0.0 <= metrics[key] <= 1.0, (
                f"{label} 指标 {key} 缺失或越界：{metrics[key]}"
            )


def test_l2_main_metrics_bite_on_skill_subset():
    """主指标口径（B1）：分母 = Skill 路径实际 skill 来源条目（⊆ 24 条
    eligible new_query 安全查询，覆盖数受 config 护栏）；模板降级路径
    （结构性不参与 + Skill 校验耗尽降级）带 marker 单列。"""
    results = _replay_suite()
    eligible_ids = l2_runner.skill_subset_ids(l2_runner.load_golden())
    assert len(eligible_ids) == _ELIGIBLE_N, "eligible 子集应恰 24 条（new_query 安全查询）"

    sources = {e["id"]: e["suggestions_source"] for e in results["entries"]}
    skill_sourced_ids = [
        e["id"]
        for e in results["entries"]
        if e["suggestions_source"] == contracts.SUGGESTIONS_SOURCE_SKILL
    ]
    assert set(skill_sourced_ids) <= set(eligible_ids), (
        f"skill 来源必须 ⊆ eligible：{sorted(set(skill_sourced_ids) - set(eligible_ids))}"
    )
    assert len(skill_sourced_ids) >= _CFG.eval.skill_coverage_min, (
        f"Skill 覆盖 {len(skill_sourced_ids)}/24 低于护栏 {_CFG.eval.skill_coverage_min}"
    )
    fallback_ids = [e["id"] for e in l2_runner.load_golden() if e["id"] not in skill_sourced_ids]
    for entry_id in fallback_ids:
        assert sources[entry_id] == contracts.SUGGESTIONS_SOURCE_TEMPLATE, (
            f"{entry_id} 属模板降级路径（结构性不参与或 Skill 校验降级），source 应为 template"
        )

    assert results["metrics"]["n_entries"] == len(skill_sourced_ids), (
        "主指标分母 = 实际 Skill 来源条目数"
    )
    assert results["metrics_template_fallback"]["n_entries"] == len(fallback_ids), (
        "模板降级 marker = 50 - 实际 Skill 来源条目数"
    )
    assert results["comparison"]["skill_eligible_ids"] == eligible_ids
    assert results["comparison"]["skill_sourced_ids"] == skill_sourced_ids
    assert sorted(results["comparison"]["fallback_ids"]) == sorted(fallback_ids)
    # 模板对照路径的同子集对账：对照数字必须来自同一组条目
    assert results["template_path"]["metrics"]["n_entries"] == len(skill_sourced_ids)


def test_l2_two_path_comparison_skill_ge_template():
    """收口条件（B1/B2 机器判定，非散文）：主指标（Skill 覆盖子集 24 条）与
    模板路径同子集对照——groundedness/relevance/actionability/specificity
    取 ≥，hallucination/矛盾率取 ≤。"""
    results = _replay_suite()
    ok = results["comparison"]["comparison_ok"]
    skill_metrics = results["comparison"]["skill_metrics"]
    template_metrics = results["comparison"]["template_metrics"]
    assert ok["groundedness"] is True, (
        f"主指标 groundedness 未跑赢模板对照：Skill {skill_metrics['groundedness_mean']:.3f} "
        f"< 模板 {template_metrics['groundedness_mean']:.3f}（B1 定案：迭代到打得过再收）"
    )
    assert ok["hallucination"] is True, (
        f"主指标幻觉率高于模板对照：Skill {skill_metrics['hallucination_rate']:.3f} "
        f"> 模板 {template_metrics['hallucination_rate']:.3f}"
    )
    assert ok["relevance"] is True, (
        f"主指标 relevance 未跑赢模板对照：Skill {skill_metrics['relevance_mean']:.3f} "
        f"< 模板 {template_metrics['relevance_mean']:.3f}"
    )
    # B2 质量维度收口（issue 05）：同子集确定性三维对照
    quality_skill = results["comparison"]["quality_skill_metrics"]
    quality_template = results["comparison"]["quality_template_metrics"]
    assert ok["actionability"] is True, (
        f"主指标 actionability 未跑赢模板对照：Skill "
        f"{quality_skill['actionability_mean']:.3f} < 模板 {quality_template['actionability_mean']:.3f}"
    )
    assert ok["specificity"] is True, (
        f"主指标 specificity 未跑赢模板对照：Skill "
        f"{quality_skill['specificity_mean']:.3f} < 模板 {quality_template['specificity_mean']:.3f}"
    )
    assert ok["contradiction"] is True, (
        f"主指标矛盾率高于模板对照：Skill {quality_skill['contradiction_rate']:.3f} "
        f"> 模板 {quality_template['contradiction_rate']:.3f}"
    )


def test_l2_quality_dimensions_b2():
    """B2 质量维度（issue 05）：逐条 quality 形状 + 主指标回归门（config
    eval.quality 的 min_*/max_*，机器断言非散文）+ 两路径同子集聚合。"""
    results = _replay_suite()
    for label, entries in (
        ("主路径（Skill）", results["entries"]),
        ("对照路径（模板）", results["template_path"]["entries"]),
    ):
        for entry in entries:
            quality = entry["quality"]
            if entry["expect_type"] == "safety":
                assert quality is not None, f"{label} {entry['id']} 缺 quality"
                assert set(quality) == {
                    "actionability",
                    "specificity",
                    "contradictions",
                    "n_suggestions",
                }, f"{entry['id']} quality 键漂移：{sorted(quality)}"
                assert 0.0 <= quality["actionability"] <= 1.0
                assert 0.0 <= quality["specificity"] <= 1.0
                assert isinstance(quality["contradictions"], list)
                assert quality["n_suggestions"] >= 0
            else:
                assert quality is None, (
                    f"{label} {entry['id']} 非 safety 形态不应有质量面"
                )

    q = results["quality"]
    assert set(q) == {"main", "template"}
    for label, metrics in (("main", q["main"]), ("template", q["template"])):
        assert set(metrics) == {
            "actionability_mean",
            "specificity_mean",
            "contradiction_rate",
            "n_entries",
        }
        assert 0.0 <= metrics["actionability_mean"] <= 1.0
        assert 0.0 <= metrics["specificity_mean"] <= 1.0
        assert 0.0 <= metrics["contradiction_rate"] <= 1.0

    # 回归门（主指标 = Skill 路径；config eval.quality 单一事实源）
    gates = _CFG.eval.quality
    assert q["main"]["actionability_mean"] >= gates.min_actionability, (
        f"actionability 主指标 {q['main']['actionability_mean']:.3f} 低于回归门 "
        f"{gates.min_actionability}（Skill 产出非行动性建议的系统性回归）"
    )
    assert q["main"]["specificity_mean"] >= gates.min_specificity, (
        f"specificity 主指标 {q['main']['specificity_mean']:.3f} 低于回归门 "
        f"{gates.min_specificity}（建议失去本区数据锚定的系统性回归）"
    )
    assert q["main"]["contradiction_rate"] <= gates.max_contradiction_rate, (
        f"矛盾率 {q['main']['contradiction_rate']:.3f} 高于回归门 "
        f"{gates.max_contradiction_rate}（建议与 charts 昼夜数据矛盾）"
    )


def test_l2_replay_matches_recorded_results_artifact():
    """同一 cassette 任何机器上回放产出同一结果：回放对账录制工件（复现性）。"""
    artifact_path = l2_runner.RESULTS_PATH
    assert artifact_path.exists(), (
        f"缺少 {artifact_path.name}（录制时由 scripts/record_l2_cassette.py 落盘）"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    replayed = _replay_suite()
    assert replayed == artifact, (
        "回放判定与录制工件不一致：提示词/模板/金标已变更但 cassette 未重新录制"
    )


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
