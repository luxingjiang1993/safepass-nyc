"""票 10 / M3 验收测试：合成用户预检脚本（spec v2 user story 25/26）。

对应 .scratch/safepass-phase2-tickets/issues/10-synthetic-user-precheck.md 四条勾选：
    1. 合成用户脚本可运行，persona 提示词 + 输出 schema 齐备
    2. 产出带"开发参考"标注（标注是装配层盖章，单一事实源在配置）
    3. 测试走 fake，离线可跑（零真实 API 调用）
    4. 人工前置：运行需 DashScope key（脚本缺 key 明确失败，本文件有端到端断言）

预检走输出控制管线模式（spec v2「合成用户」节）：生成 → 解析 → 校验
→ 有限重试（上界 = config output_pipeline.max_retries）→ 明确失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from safepass import config_loader, synthetic_user
from safepass.llm_client import ChatResponse
from safepass.output_pipeline import BusinessValidationError, OutputPipelineError

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT = REPO_ROOT / "scripts" / "run_synthetic_precheck.py"


class _ScriptedFakeLLM:
    """按剧本逐条返回的 fake；记录每次调用收到的完整消息列表。"""

    def __init__(self, script: list[str]):
        self._script = list(script)
        self.calls = 0
        self.seen_messages: list[list[dict[str, str]]] = []

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        self.seen_messages.append([dict(m) for m in messages])
        if not self._script:
            raise AssertionError("fake LLM 剧本耗尽：调用次数超出预期（重试无上界？）")
        return ChatResponse(content=self._script.pop(0), model="fake")


def _reply_payload(text: str) -> str:
    return json.dumps({"reply": text}, ensure_ascii=False)


def _tiny_script(cfg) -> synthetic_user.InterviewScript:
    """两题的迷你脚本：让 fake 剧本短、断言聚焦。"""
    return synthetic_user.InterviewScript(
        version="test",
        questions=(
            synthetic_user.InterviewQuestion(id="tq1", question="你会立刻用它查什么？"),
            synthetic_user.InterviewQuestion(id="tq2", question="哪条建议你觉得是废话？"),
        ),
    )


def test_personas_cover_three_target_crowds():
    """persona 提示词齐备：三类目标人群（留学生 / 新移民 / 访客）各有专属 persona。"""
    text = " ".join(p.background for p in synthetic_user.PERSONAS)
    for crowd in ("留学生", "新移民", "访客"):
        assert crowd in text, f"persona 清单缺少目标人群：{crowd}"
    ids = [p.id for p in synthetic_user.PERSONAS]
    assert len(ids) == len(set(ids)), "persona id 必须唯一"


def test_interview_script_fixture_loads():
    """访谈脚本草稿（票 11 前身资产）可被预检加载：题号唯一、题面非空。"""
    cfg = config_loader.load_config()
    script = synthetic_user.load_interview_script(cfg)
    assert len(script.questions) >= 5, "访谈脚本题量过少，不足以预戳"
    ids = [q.id for q in script.questions]
    assert len(ids) == len(set(ids)), "访谈脚本题号必须唯一"
    for q in script.questions:
        assert q.question.strip(), f"题面为空：{q.id}"


def test_precheck_runs_all_personas_and_stamps_label(tmp_path):
    """勾选 1+2：预检可运行（fake），全部产出带配置里的"开发参考"标注。"""
    cfg = config_loader.load_config()
    script = _tiny_script(cfg)
    total = len(synthetic_user.PERSONAS) * len(script.questions)
    fake = _ScriptedFakeLLM([_reply_payload("先查法拉盛晚上逛街安不安全。")] * total)

    report = synthetic_user.run_precheck(fake, script, cfg)

    assert report["label"] == cfg.synthetic_user.dev_reference_label == "开发参考"
    assert "永不冒充真人证据" in report["note"]
    assert report["model"] == cfg.synthetic_user.model
    assert len(report["answers"]) == total
    for answer in report["answers"]:
        assert answer["label"] == "开发参考", "每条回答都必须带开发参考标注"
        assert answer["reply"].strip()
    assert fake.calls == total, "合法输出不应触发重试"


def test_persona_prompt_contains_background_and_json_instruction():
    """persona 提示词齐备：背景注入题面，且要求 JSON 结构化输出（管线契约）。"""
    cfg = config_loader.load_config()
    script = _tiny_script(cfg)
    fake = _ScriptedFakeLLM(
        [_reply_payload("回答")] * (len(synthetic_user.PERSONAS) * len(script.questions))
    )
    synthetic_user.run_precheck(fake, script, cfg)

    first_call = fake.seen_messages[0]
    assert any("留学生" in m["content"] or "新移民" in m["content"] or "访客" in m["content"]
               for m in first_call), "提示词必须注入 persona 背景"
    assert any("JSON" in m["content"] for m in first_call), "提示词必须要求 JSON 输出"


def test_corrupt_llm_retries_bounded_then_fails():
    """勾选 3 的管线语义：解析失败走有限重试，次数 = 1 + 配置上界，耗尽明确失败。"""
    cfg = config_loader.load_config()
    script = _tiny_script(cfg)
    fake = _ScriptedFakeLLM([])  # 剧本为空：任何调用都会先记录再抛 AssertionError
    corrupt = _AlwaysCorruptLLM()
    with pytest.raises(OutputPipelineError):
        synthetic_user.run_precheck(corrupt, script, cfg)
    assert corrupt.calls == 1 + cfg.max_retries


def test_oversized_reply_is_business_validation_failure_then_retry_recovers():
    """业务校验：超长回答被拒并回灌重试；修正后同一次调用收敛（反馈环真实生效）。"""
    cfg = config_loader.load_config()
    assert cfg.synthetic_user.reply_max_chars > 0
    long_reply = "字" * (cfg.synthetic_user.reply_max_chars + 1)
    fake = _ScriptedFakeLLM(
        [_reply_payload(long_reply), _reply_payload("正常回答。"), _reply_payload("第二题回答。")]
    )
    answer = synthetic_user.run_persona(
        fake, synthetic_user.PERSONAS[0], _tiny_script(cfg).questions, cfg
    )
    assert answer[0]["reply"] == "正常回答。"
    assert answer[1]["reply"] == "第二题回答。"
    assert fake.calls == 3  # 第 1 题重试 1 次 + 第 2 题一次通过

    with pytest.raises(BusinessValidationError):
        synthetic_user.validate_reply_length(
            synthetic_user.SyntheticReply(reply=long_reply), cfg
        )


def test_write_report_roundtrip_carries_label(tmp_path):
    """勾选 2 落盘侧：报告 JSON 头与每条记录都带标注，文件可直接进证据链。"""
    cfg = config_loader.load_config()
    script = _tiny_script(cfg)
    total = len(synthetic_user.PERSONAS) * len(script.questions)
    fake = _ScriptedFakeLLM([_reply_payload("回答")] * total)
    report = synthetic_user.run_precheck(fake, script, cfg)

    out = tmp_path / "synthetic_precheck_test.json"
    synthetic_user.write_report(report, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["label"] == "开发参考"
    assert all(a["label"] == "开发参考" for a in loaded["answers"])


def test_run_script_fails_without_dashscope_key():
    """勾选 4（人工前置）：脚本无 DASHSCOPE_API_KEY 时明确失败并给出提示，不静默。"""
    env = {k: v for k, v in os.environ.items() if k != "DASHSCOPE_API_KEY"}
    result = subprocess.run(
        [sys.executable, str(RUN_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "DASHSCOPE_API_KEY" in (result.stdout + result.stderr)


class _AlwaysCorruptLLM:
    """无论多少次调用都返回不可解析内容的 fake（重试上界探针）。"""

    def __init__(self, content: str = "这不是 JSON，也不是对象"):
        self._content = content
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(content=self._content, model="fake")
