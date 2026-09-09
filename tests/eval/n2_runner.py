"""N2b 三列对照 runner（issue 26）：裸 LLM / 无约束 RAG / SafePass。

与 L2 分家：本模块只生成对照列文本并用 N2a 纯函数打分，不调用 L2 judge。
生成 cassette 与 L2 judge/skill cassette 分文件。测试世界钉 mock 数据集
（l2_runner / conftest 同款钉子）。对照列实现不进主应用依赖。

录制：scripts/record_n2_cassette.py（需 DASHSCOPE_API_KEY）
回放：tests/eval/test_n2_three_column.py（零网络）
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from safepass import config_loader, contracts, data_agent
from safepass.degraded import RATING_LABELS
from safepass.llm_client import LLMClient, chat_with_cassette, reset_cassette_cursor
from safepass.pipeline import _retrieval_snippets

import l2_runner
import n2_scorers

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = l2_runner.GOLDEN_PATH
RESULTS_PATH = REPO_ROOT / "fixtures" / "eval" / "n2_results_v1.json"
REPORT_PATH = REPO_ROOT / "docs" / "baseline-vs-safepass.md"

# 生成 cassette 与 L2 分文件（禁止写入 l2_judge*.json / l2_skill.json）
BARE_CASSETTE = REPO_ROOT / "tests" / "cassettes" / "n2_bare.json"
RAG_CASSETTE = REPO_ROOT / "tests" / "cassettes" / "n2_rag.json"
SAFEPASS_CASSETTE = REPO_ROOT / "tests" / "cassettes" / "n2_safepass.json"

# 与 conftest / l2_runner 同值：录制脚本不经 pytest 时也钉 mock 世界
MOCK_DATASET_PATH = l2_runner.MOCK_DATASET_PATH
os.environ[data_agent.DATASET_PATH_ENV] = str(MOCK_DATASET_PATH)

COLUMN_BARE = "bare"
COLUMN_RAG = "rag"
COLUMN_SAFEPASS = "safepass"
COLUMNS = (COLUMN_BARE, COLUMN_RAG, COLUMN_SAFEPASS)

# 对照列提示：不禁写灯、不塞图表/全市倍数；画像不进供应商请求。
# 要求写出产品四级标签与案件量数字，才能被 N2a 尺子抓住——对应「会调 API
# 的聊天机器人」常见系统指令（请给评级和数字），不是故意劣化检索。
_BARE_SYSTEM = (
    "你是通用问答助手，用中文直接回答用户关于纽约某地是否安全的问题。"
    "必须给出安全评级，写成「安全评级：相对安全」或「安全评级：需注意」"
    "或「安全评级：高风险」或「安全评级：数据不足」四选一。"
    "并写出你掌握的具体案件量（如「xx起」）或犯罪率数字。"
)
_RAG_SYSTEM = (
    "你是通用问答助手。用户消息附有检索到的知识文档全文。"
    "请用中文回答；文档未写明的内容也可以按常识补充，不要注入统计表。"
    "必须给出安全评级，写成「安全评级：相对安全」或「安全评级：需注意」"
    "或「安全评级：高风险」或「安全评级：数据不足」四选一。"
    "并写出具体案件量（如「xx起」）或犯罪率数字（文档没有数字时按常识补上）。"
)

_COMPARISON_CHAT_KWARGS = {"temperature": 0}
_FAILURE_SAMPLE_N = 3


def load_n2_golden_entries() -> tuple[dict[str, Any], ...]:
    """按 N2a 夹具顺序取出二十条金标（改名单由 N2a 测试先红）。"""
    subset = n2_scorers.load_n2_subset()
    by_id = {e["id"]: e for e in l2_runner.load_golden()}
    missing = [i for i in subset.all_ids if i not in by_id]
    if missing:
        raise ValueError(f"N2 子集 ID 不在金标中：{missing}")
    return tuple(by_id[i] for i in subset.all_ids)


def rag_evidence_text(query: str) -> str:
    """无约束 RAG 证据 = 产品同一混合检索 top-3 知识文档整段（不劣化检索）。"""
    snippets = _retrieval_snippets(query)
    return "\n\n".join(f"【{s.doc_id}】\n{s.text}" for s in snippets)


def _bare_messages(query: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _BARE_SYSTEM},
        {"role": "user", "content": query},
    ]


def _rag_messages(query: str, evidence: str) -> list[dict[str, str]]:
    user = f"{query}\n\n【检索到的知识文档】\n{evidence}"
    return [
        {"role": "system", "content": _RAG_SYSTEM},
        {"role": "user", "content": user},
    ]


def _comparison_chat(
    client: LLMClient,
    cassette: Path,
    messages: list[dict[str, str]],
    *,
    model: str,
    record: bool,
) -> str:
    response = chat_with_cassette(
        client,
        cassette,
        messages,
        model=model,
        record=record,
        **_COMPARISON_CHAT_KWARGS,
    )
    return response.content or ""


def render_safepass_text(result: contracts.ResponseContract) -> str:
    """SafePass 列打分文本：用户可见结论与建议；越界不含替代区评级（避免误判编造）。"""
    if isinstance(result, contracts.SafetyQueryResult):
        return "\n".join([result.one_liner, *result.suggestions])
    if isinstance(result, contracts.DegradedResult):
        parts = [result.message, result.reselection_invitation, *result.general_suggestions]
        return "\n".join(p for p in parts if p)
    raise TypeError(f"N2 子集不应出现形态 {type(result).__name__}")


def safepass_evidence_text(
    result: contracts.ResponseContract,
    query: str,
) -> str:
    """SafePass 证据：检索摘要 + 图表可核对数字/灯色；越界证据为空。"""
    if isinstance(result, contracts.DegradedResult):
        return ""
    if not isinstance(result, contracts.SafetyQueryResult):
        raise TypeError(f"覆盖内证据只接受 SafetyQueryResult，收到 {type(result).__name__}")
    parts: list[str] = [rag_evidence_text(query)]
    parts.append(RATING_LABELS[result.rating])
    if result.rating_explainable_basis is not None:
        ratio = result.rating_explainable_basis
        parts.append(f"{ratio:.1f}倍")
        parts.append(f"{ratio:.2f} 倍")
    if result.charts is not None:
        parts.append(f"{result.charts.day_night.day}起")
        parts.append(f"{result.charts.day_night.night}起")
        for item in result.charts.top5_types:
            parts.append(f"{item.count}起")
    parts.append(f"{result.sample_size}起")
    return "\n".join(parts)


def _score_column(
    output: str,
    evidence: str,
    *,
    out_of_coverage: bool,
    expected_rating: str | None,
) -> dict[str, Any]:
    unevidenced = n2_scorers.has_unevidenced_factual_claim(output, evidence)
    fabricated = (
        n2_scorers.is_out_of_coverage_fabrication(output) if out_of_coverage else False
    )
    rating = n2_scorers.score_rating_consistency(
        output, None if out_of_coverage else expected_rating
    )
    return {
        "output": output,
        "unevidenced_factual_claim": unevidenced,
        "out_of_coverage_fabrication": fabricated,
        "rating_consistency": rating,
    }


def _aggregate(per_entry: list[dict[str, Any]], subset: n2_scorers.N2Subset) -> dict[str, Any]:
    n = len(per_entry)
    ooc_ids = set(subset.out_of_coverage_ids)
    in_ids = set(subset.in_coverage_ids)
    metrics: dict[str, Any] = {"n_entries": n}
    for col in COLUMNS:
        unevidenced_n = sum(
            1 for e in per_entry if e["columns"][col]["unevidenced_factual_claim"]
        )
        ooc_fab_n = sum(
            1
            for e in per_entry
            if e["id"] in ooc_ids and e["columns"][col]["out_of_coverage_fabrication"]
        )
        in_rows = [e for e in per_entry if e["id"] in in_ids]
        match_n = sum(
            1
            for e in in_rows
            if e["columns"][col]["rating_consistency"] == n2_scorers.RATING_MATCH
        )
        metrics[col] = {
            "unevidenced_factual_claim_rate": unevidenced_n / n,
            "unevidenced_factual_claim_n": unevidenced_n,
            "out_of_coverage_fabrication_n": ooc_fab_n,
            "out_of_coverage_fabrication_rate": ooc_fab_n / len(subset.out_of_coverage_ids),
            "rating_consistency_rate": match_n / len(in_rows),
            "rating_consistency_n": match_n,
            "in_coverage_n": len(in_rows),
        }
    sp = metrics[COLUMN_SAFEPASS]
    bare = metrics[COLUMN_BARE]
    rag = metrics[COLUMN_RAG]
    metrics["closure"] = {
        "safepass_unevidenced_lt_bare": (
            sp["unevidenced_factual_claim_rate"] < bare["unevidenced_factual_claim_rate"]
        ),
        "safepass_unevidenced_lt_rag": (
            sp["unevidenced_factual_claim_rate"] < rag["unevidenced_factual_claim_rate"]
        ),
        "safepass_ooc_fabrication_zero": sp["out_of_coverage_fabrication_n"] == 0,
        "bare_ooc_fabrication_ge_1": bare["out_of_coverage_fabrication_n"] >= 1,
        "rag_ooc_fabrication_ge_1": rag["out_of_coverage_fabrication_n"] >= 1,
        "safepass_rating_consistency_100": sp["rating_consistency_rate"] == 1.0,
    }
    return metrics


def _pick_failure_samples(per_entry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对照列翻车、SafePass 做对的样例（确定性：按金标顺序取满 3 条）。"""
    samples: list[dict[str, Any]] = []
    for row in per_entry:
        sp = row["columns"][COLUMN_SAFEPASS]
        if sp["unevidenced_factual_claim"] or sp["out_of_coverage_fabrication"]:
            continue
        if (
            row["expect_type"] == "safety"
            and sp["rating_consistency"] != n2_scorers.RATING_MATCH
        ):
            continue
        bare = row["columns"][COLUMN_BARE]
        rag = row["columns"][COLUMN_RAG]
        bare_fail = bare["unevidenced_factual_claim"] or bare["out_of_coverage_fabrication"]
        rag_fail = rag["unevidenced_factual_claim"] or rag["out_of_coverage_fabrication"]
        if not (bare_fail or rag_fail):
            continue
        samples.append(
            {
                "id": row["id"],
                "query": row["query"],
                "why": (
                    "对照列给出无证据事实声明或越界编造，SafePass 未编造且覆盖内评级一致"
                ),
                "bare_excerpt": bare["output"][:280],
                "rag_excerpt": rag["output"][:280],
                "safepass_excerpt": sp["output"][:280],
            }
        )
        if len(samples) >= _FAILURE_SAMPLE_N:
            break
    return samples


def run_n2_suite(
    *,
    llm_client: LLMClient,
    cfg: config_loader.AppConfig | None = None,
    record: bool = False,
    record_safepass: bool | None = None,
) -> dict[str, Any]:
    """二十条金标三列生成 + N2a 打分。record=True 写入对照列 cassette。

    record_safepass 默认与 record 相同；对照列重录时可 False，复用已有
    n2_safepass.json（唯一接缝提示词未变）。
    """
    cfg = cfg if cfg is not None else config_loader.load_config()
    model = cfg.eval.judge_model
    subset = n2_scorers.load_n2_subset()
    ooc_ids = set(subset.out_of_coverage_ids)
    entries = load_n2_golden_entries()
    skill_record = record if record_safepass is None else record_safepass
    skill_client = l2_runner._SkillDispatchClient(
        llm_client, SAFEPASS_CASSETTE, record=skill_record
    )

    per_entry: list[dict[str, Any]] = []
    for entry in entries:
        query = entry["query"]
        ooc = entry["id"] in ooc_ids
        expected_rating = entry["expect"].get("rating")
        evidence_rag = rag_evidence_text(query)

        bare_out = _comparison_chat(
            llm_client,
            BARE_CASSETTE,
            _bare_messages(query),
            model=model,
            record=record,
        )
        rag_out = _comparison_chat(
            llm_client,
            RAG_CASSETTE,
            _rag_messages(query, evidence_rag),
            model=model,
            record=record,
        )
        result = l2_runner.run_entry(entry, skill_client=skill_client)
        if result.type != entry["expect"]["type"]:
            raise AssertionError(
                f"{entry['id']} SafePass 形态 {result.type!r} 与金标 "
                f"{entry['expect']['type']!r} 不一致"
            )
        sp_out = render_safepass_text(result)
        sp_evidence = safepass_evidence_text(result, query)

        per_entry.append(
            {
                "id": entry["id"],
                "query": query,
                "form": entry["form"],
                "expect_type": entry["expect"]["type"],
                "expected_rating": expected_rating,
                "columns": {
                    COLUMN_BARE: _score_column(
                        bare_out,
                        "",
                        out_of_coverage=ooc,
                        expected_rating=expected_rating,
                    ),
                    COLUMN_RAG: _score_column(
                        rag_out,
                        evidence_rag,
                        out_of_coverage=ooc,
                        expected_rating=expected_rating,
                    ),
                    COLUMN_SAFEPASS: _score_column(
                        sp_out,
                        sp_evidence,
                        out_of_coverage=ooc,
                        expected_rating=expected_rating,
                    ),
                },
            }
        )

    metrics = _aggregate(per_entry, subset)
    failure_samples = _pick_failure_samples(per_entry)
    return {
        "golden_version": json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["version"],
        "subset_version": json.loads(n2_scorers.SUBSET_PATH.read_text(encoding="utf-8"))[
            "version"
        ],
        "n_entries": len(per_entry),
        "safepass_cassette_interactions": skill_client.cassette_calls,
        "metrics": metrics,
        "failure_samples": failure_samples,
        "entries": per_entry,
    }


def write_results(results: dict[str, Any], path: Path = RESULTS_PATH) -> None:
    path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def render_markdown(results: dict[str, Any]) -> str:
    """对照页正文（数字与 runner 工件同源；禁止手改数字）。"""
    m = results["metrics"]
    closure = m["closure"]
    lines = [
        "# SafePass NYC — 基线对照（N2）",
        "",
        "本页回答：**和会调 API 的人差在哪**。会调检索 API 的人可以把知识文档塞进提示（无约束 RAG 列）；",
        "SafePass 多出来的是确定性评级/越界后置、建议依据校验、以及越界时拒绝编造灯色。",
        "指标是 N2a 纯函数，**不是** L2 judge 幻觉率。",
        "",
        f"- 查询集：N2a 钉死 20 条（`fixtures/eval/n2_subset_v1.json`，金标 {results['golden_version']}）",
        "- 世界：mock 数据集（与默认 pytest / L2 同一钉子）",
        "- 复现：`python -m pytest tests/eval/test_n2_three_column.py -q`（cassette 回放，零网络）",
        "- 重录：`python scripts/record_n2_cassette.py`（需 `DASHSCOPE_API_KEY`；勿动 L2 cassette）",
        "- 默认 `python -m pytest tests/ -q` **不跑** 本套件",
        "",
        "## 三列数字",
        "",
        "| 列 | 无证据事实声明率 | 越界编造（7 条子集） | 覆盖内评级一致性 |",
        "|---|---|---|---|",
    ]
    labels = {
        COLUMN_BARE: "裸 LLM（无检索）",
        COLUMN_RAG: "无约束 RAG（同一混合检索 top-3）",
        COLUMN_SAFEPASS: "SafePass（唯一接缝）",
    }
    for col in COLUMNS:
        row = m[col]
        lines.append(
            "| {name} | {u:.3f}（{un}/{n}） | {fn} / 7（{fr:.3f}） | {rr:.3f}（{rn}/{inn}） |".format(
                name=labels[col],
                u=row["unevidenced_factual_claim_rate"],
                un=row["unevidenced_factual_claim_n"],
                n=m["n_entries"],
                fn=row["out_of_coverage_fabrication_n"],
                fr=row["out_of_coverage_fabrication_rate"],
                rr=row["rating_consistency_rate"],
                rn=row["rating_consistency_n"],
                inn=row["in_coverage_n"],
            )
        )
    lines.extend(
        [
            "",
            "## 布尔收口",
            "",
            f"- SafePass 无证据事实声明率 < 裸 LLM：{'是' if closure['safepass_unevidenced_lt_bare'] else '否'}",
            f"- SafePass 无证据事实声明率 < 无约束 RAG：{'是' if closure['safepass_unevidenced_lt_rag'] else '否'}",
            f"- SafePass 越界编造次数 = 0：{'是' if closure['safepass_ooc_fabrication_zero'] else '否'}",
            f"- 裸 LLM 越界子集编造 ≥ 1：{'是' if closure['bare_ooc_fabrication_ge_1'] else '否'}",
            f"- 无约束 RAG 越界子集编造 ≥ 1：{'是' if closure['rag_ooc_fabrication_ge_1'] else '否'}",
            f"- SafePass 覆盖内评级一致性 = 100%：{'是' if closure['safepass_rating_consistency_100'] else '否'}",
            "",
            "## 失败样例（对照列翻车，SafePass 做对）",
            "",
        ]
    )
    samples = results["failure_samples"]
    if len(samples) < _FAILURE_SAMPLE_N:
        lines.append(
            f"样例不足 {_FAILURE_SAMPLE_N} 条（实际 {len(samples)}）。重录对照列或检查打分口径。"
        )
    for i, sample in enumerate(samples, start=1):
        lines.extend(
            [
                f"### {i}. {sample['id']} — {sample['query']}",
                "",
                sample["why"],
                "",
                "**裸 LLM**",
                "",
                "```",
                sample["bare_excerpt"],
                "```",
                "",
                "**无约束 RAG**",
                "",
                "```",
                sample["rag_excerpt"],
                "```",
                "",
                "**SafePass**",
                "",
                "```",
                sample["safepass_excerpt"],
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## 口径备忘",
            "",
            "- 裸 LLM：证据为空；无约束 RAG：证据 = 所塞 top-3 原文；SafePass：证据 = 检索摘要 + 图表可核对字段。",
            "- 无约束 RAG 不注入图表、不注入相对全市倍数、不换更差检索器、不做依据逐字校验。",
            "- SafePass 列只打 `execute_query`；对照列只存在于本评测模块。",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(results: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.write_text(render_markdown(results), encoding="utf-8")


def reset_n2_cassettes() -> None:
    """回放前把三份生成 cassette 游标归零。"""
    reset_cassette_cursor(BARE_CASSETTE)
    reset_cassette_cursor(RAG_CASSETTE)
    reset_cassette_cursor(SAFEPASS_CASSETTE)
