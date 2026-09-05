"""L2 evaluator 机械性测试（issue 03 / M1）：judge 构造/解析/配置锁定/cassette 资产。

打 `safepass/evaluators.py` 与配置锁定的行为面，不碰真实网络：
judge 客户端一律注入 fake；cassette 资产完整性沿用既有自检模式
（tests/test_chinese_address.py::test_extraction_cassette_asset_wellformed）。

运行（独立套件，不进默认基线）：``pytest tests/eval -q``
"""

from __future__ import annotations

import json
import re

import pytest

from safepass import config_loader, evaluators
from safepass.llm_client import ChatResponse

pytestmark = pytest.mark.eval

_CFG = config_loader.load_config()


class _ScriptedJudge:
    """剧本 judge：按序返回预置内容（机械性测试零网络）。"""

    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.calls = 0
        self.seen_models: list[str | None] = []
        self.seen_kwargs: list[dict] = []

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        self.seen_models.append(model)
        self.seen_kwargs.append(kwargs)
        if not self._contents:
            raise AssertionError("剧本 judge 被超额调用")
        return ChatResponse(content=self._contents.pop(0), model=model or "")


def test_prompt_versions_locked_for_all_three_evaluators():
    """三类 evaluator 的提示词版本全部锁定进 config（spec：基准不随依赖漂移）。"""
    for key in evaluators.LEGAL_FEEDBACK_KEYS:
        version = _CFG.eval.prompt_versions.get(key)
        assert isinstance(version, str) and version.strip(), f"{key} 缺版本锁定"
        assert re.fullmatch(r"sp-[a-z]+-v\d+", version), f"{key} 版本串格式异常：{version}"


def test_config_carries_judge_model_and_threshold():
    """judge 模型名与通过分数线锁定进 config，代码零字面量。"""
    assert _CFG.eval.judge_model.strip()
    assert _CFG.eval.base_url.strip()
    assert 0.0 < _CFG.eval.pass_threshold <= 1.0
    assert _CFG.eval.cassette.strip()


def test_evaluator_rejects_unknown_feedback_key():
    with pytest.raises(evaluators.JudgeError):
        evaluators.build_evaluator(
            "toxicity", judge_client=_ScriptedJudge([]), cfg=_CFG
        )


def test_evaluator_renders_slots_and_parses_verdict():
    judge = _ScriptedJudge(['{"score": 0.9, "reason": "全部声明有依据"}'])
    evaluator = evaluators.build_evaluator(
        evaluators.FEEDBACK_GROUNDEDNESS, judge_client=judge, cfg=_CFG
    )
    verdict = evaluator(
        inputs="法拉盛安全吗",
        outputs="{\"rating\": \"yellow\"}",
        evidence="{\"rating\": \"yellow\"}",
        reference="{\"must_mention\": []}",
    )
    assert verdict.feedback_key == evaluators.FEEDBACK_GROUNDEDNESS
    assert verdict.score == pytest.approx(0.9)
    assert verdict.reason
    assert verdict.prompt_version == _CFG.eval.prompt_versions["groundedness"]
    assert verdict.judge_model == _CFG.eval.judge_model
    # 考官调用形态对齐改写来源（temperature=0，model 走 config 锁定）
    assert judge.seen_models == [_CFG.eval.judge_model]
    assert judge.seen_kwargs == [{"temperature": 0}]


def test_evaluator_rejects_out_of_range_score():
    judge = _ScriptedJudge(['{"score": 1.4, "reason": "考官手滑"}'])
    evaluator = evaluators.build_evaluator(
        evaluators.FEEDBACK_RELEVANCE, judge_client=judge, cfg=_CFG
    )
    with pytest.raises(evaluators.JudgeError):
        evaluator(inputs="q", outputs="a")


def test_hallucination_verdict_derives_binary_score_from_boolean():
    judge = _ScriptedJudge(
        ['{"hallucinated": true, "reason": "出现了禁止声明"}']
    )
    evaluator = evaluators.build_evaluator(
        evaluators.FEEDBACK_HALLUCINATION, judge_client=judge, cfg=_CFG
    )
    verdict = evaluator(inputs="q", outputs="a")
    assert verdict.score == 0.0
    judge2 = _ScriptedJudge(['{"hallucinated": false, "reason": "无幻觉"}'])
    evaluator2 = evaluators.build_evaluator(
        evaluators.FEEDBACK_HALLUCINATION, judge_client=judge2, cfg=_CFG
    )
    assert evaluator2(inputs="q", outputs="a").score == 1.0


def test_judge_rejects_unparseable_output():
    judge = _ScriptedJudge(["这不是 JSON"])
    evaluator = evaluators.build_evaluator(
        evaluators.FEEDBACK_GROUNDEDNESS, judge_client=judge, cfg=_CFG
    )
    with pytest.raises(evaluators.JudgeError):
        evaluator(inputs="q", outputs="a")


def test_judge_rejects_missing_reason():
    judge = _ScriptedJudge(['{"score": 1.0}'])
    evaluator = evaluators.build_evaluator(
        evaluators.FEEDBACK_GROUNDEDNESS, judge_client=judge, cfg=_CFG
    )
    with pytest.raises(evaluators.JudgeError):
        evaluator(inputs="q", outputs="a")


def test_judge_rejects_non_boolean_hallucinated():
    judge = _ScriptedJudge(['{"hallucinated": "yes", "reason": "x"}'])
    evaluator = evaluators.build_evaluator(
        evaluators.FEEDBACK_HALLUCINATION, judge_client=judge, cfg=_CFG
    )
    with pytest.raises(evaluators.JudgeError):
        evaluator(inputs="q", outputs="a")


def test_aggregate_produces_three_metrics():
    verdicts = [
        evaluators.JudgeVerdict("groundedness", 1.0, "ok", "v", "m"),
        evaluators.JudgeVerdict("groundedness", 0.5, "half", "v", "m"),
        evaluators.JudgeVerdict("relevance", 0.8, "ok", "v", "m"),
        evaluators.JudgeVerdict("hallucination", 0.0, "bad", "v", "m"),
        evaluators.JudgeVerdict("hallucination", 1.0, "ok", "v", "m"),
    ]
    threshold = _CFG.eval.pass_threshold  # 红线 1：阈值字面量只活在 config
    metrics = evaluators.aggregate(verdicts, pass_threshold=threshold)
    assert metrics["groundedness_mean"] == pytest.approx(0.75)
    assert metrics["groundedness_pass_rate"] == pytest.approx(0.5)
    assert metrics["relevance_mean"] == pytest.approx(0.8)
    assert metrics["hallucination_rate"] == pytest.approx(0.5)
    assert metrics["pass_threshold"] == threshold


def test_provenance_annotations_present():
    """改写来源逐组件标注（docs/phase2-skills.md 硬性要求）：模块与三模板均带来源。"""
    import inspect

    source = inspect.getsource(evaluators)
    assert "CASE-openevals使用/5-rag_groundedness.py" in source
    assert "CASE-openevals使用/8-hallucination.py" in source
    assert "CASE-openevals使用/3-answer_relevance.py" in source
