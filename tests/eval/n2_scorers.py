"""N2 对照三项确定性打分（issue 28 / N2a）。

评测专用纯函数：无证据事实声明、越界编造、评级一致性。不进产品路由、
不调用 LLM、不复用 L2 幻觉 judge。对照列生成器在 N2b，本模块只交尺子。

夹具单一事实源：fixtures/eval/n2_subset_v1.json（改名单即红）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from safepass.degraded import RATING_LABELS

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSET_PATH = REPO_ROOT / "fixtures" / "eval" / "n2_subset_v1.json"

# 具体案件量：阿拉伯数字 + 中文计量（起/件/条）。不把「12个月」「911」当案件量。
_CASE_COUNT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:起|件|条)")
# 犯罪率数字：犯罪率/案件量/案发率邻近数字，或「N倍」相对全市口径。
_CRIME_RATE_RE = re.compile(r"(?:犯罪率|案件量|案发率)[^。\n]{0,16}\d|\d+(?:\.\d+)?\s*倍")


@dataclass(frozen=True)
class N2Subset:
    """钉死的对照查询 ID 名单（覆盖内 / 越界互斥，顺序与夹具一致）。"""

    in_coverage_ids: tuple[str, ...]
    out_of_coverage_ids: tuple[str, ...]

    @property
    def all_ids(self) -> tuple[str, ...]:
        return self.in_coverage_ids + self.out_of_coverage_ids


def load_n2_subset(path: Path = SUBSET_PATH) -> N2Subset:
    """加载 N2 子集夹具。"""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    in_ids = tuple(payload["in_coverage_ids"])
    ooc_ids = tuple(payload["out_of_coverage_ids"])
    return N2Subset(in_coverage_ids=in_ids, out_of_coverage_ids=ooc_ids)


def _rating_name(label: str) -> str:
    """从「灯色 + 空格 + 四级标签」里取出四级标签本身。"""
    parts = label.split(None, 1)
    return parts[-1] if parts else label


def _rating_light(label: str) -> str:
    """灯色标记（来自产品 RATING_LABELS，本模块不另写字面量）。"""
    parts = label.split(None, 1)
    return parts[0] if len(parts) == 2 else ""


def _stated_rating_span(text: str, label: str) -> str | None:
    """判定四级结论：完整产品标签、灯色、或「评级/冒号」锚定的四级名。

    裸「需注意」「数据不足」出现在建议里不算已输出评级（避免短标签误伤）。
    """
    name = _rating_name(label)
    light = _rating_light(label)
    if label in text:
        return label
    if light and light in text:
        return light
    if re.search(rf"(?:安全评级|评级)\s*[为:：]?\s*{re.escape(name)}", text):
        return name
    if f"：{name}" in text or f":{name}" in text:
        return name
    return None


def stated_rating_keys(text: str) -> tuple[str, ...]:
    """输出中出现的四级安全评级枚举键（可多枚；顺序按 RATING_LABELS）。"""
    found: list[str] = []
    for key, label in RATING_LABELS.items():
        if _stated_rating_span(text, label):
            found.append(key)
    return tuple(found)


def factual_claim_spans(text: str) -> tuple[str, ...]:
    """输出里的事实声明片段：四级评级标签、案件量、犯罪率数字。"""
    spans: list[str] = []
    for _key, label in RATING_LABELS.items():
        span = _stated_rating_span(text, label)
        if span:
            spans.append(span)
    spans.extend(_CASE_COUNT_RE.findall(text))
    spans.extend(_CRIME_RATE_RE.findall(text))
    return tuple(spans)


def has_unevidenced_factual_claim(output: str, evidence: str) -> bool:
    """无证据事实声明：出现犯罪数字、四级安全评级或具体案件量，却无对应证据。

    裸 LLM 证据为空；无约束 RAG 以所塞片段为证据。某声明片段须作为子串
    出现在证据里才算有依据——不做语义改写、不调用 judge。
    """
    claims = factual_claim_spans(output)
    if not claims:
        return False
    evid = evidence.strip()
    if not evid:
        return True
    return any(span not in evid for span in claims)


RATING_UNRATED = "未评级"
RATING_MATCH = "一致"
RATING_MISMATCH = "不一致"


def is_out_of_coverage_fabrication(output: str) -> bool:
    """越界编造：仍给出该地点的安全评级或犯罪率数字。

    诚实降级可提及「无法给出安全评级」，只要不出现四级标签与犯罪数字。
    """
    if stated_rating_keys(output):
        return True
    if _CASE_COUNT_RE.search(output) or _CRIME_RATE_RE.search(output):
        return True
    return False


def score_rating_consistency(output: str, expected_rating: str | None) -> str:
    """评级一致性：输出灯色/四级结论则与期望枚举对账；未输出记未评级。"""
    stated = stated_rating_keys(output)
    if not stated:
        return RATING_UNRATED
    unique = set(stated)
    if expected_rating is None or unique != {expected_rating}:
        return RATING_MISMATCH
    return RATING_MATCH
