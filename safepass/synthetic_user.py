"""合成用户预检（票 10 / M3，spec v2「合成用户」节）。

LLM 扮演目标用户 persona（留学生 / 新移民 / 访客），在产品真人访谈前
低成本预戳访谈脚本草稿（fixtures/eval/interview_script_v1.json）：暴露
引导性/歧义性问题、扩充金标输入。

输出控制管线模式（spec v2「合成用户」节）：生成 → 解析 → 校验 → 有限
重试（上界 = config output_pipeline.max_retries，单一事实源）→ 明确失败。
重试上界、模型路由、标注、字数上界全部经 config_loader 读取（红线 1）。

**诚实红线**：全部产出必须带 dev_reference_label 标注（配置单一事实源），
报告头与每条回答都盖章——合成用户永不冒充真人证据。本模块 dev-only，
不进入生产路径；生产接线见 safepass.llm_wiring（票 12）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from safepass import config_loader
from safepass.llm_client import LLMClient
from safepass.output_pipeline import (
    BusinessValidationError,
    run_pipeline,
)


@dataclass(frozen=True)
class Persona:
    """一个目标用户 persona：id 唯一，background 注入提示词扮演背景。"""

    id: str
    background: str


@dataclass(frozen=True)
class InterviewQuestion:
    """访谈脚本单题：题号唯一（加载时校验），题面非空。"""

    id: str
    question: str


@dataclass(frozen=True)
class InterviewScript:
    """访谈脚本草稿（票 11 前身资产，票 10 先用它低成本试戳）。"""

    version: str
    questions: tuple[InterviewQuestion, ...]


class SyntheticReply(BaseModel):
    """管线契约：合成用户对单题的回答（结构化 JSON 输出）。"""

    reply: str


# 三类目标人群各一个专属 persona（spec 用户画像；背景注入提示词）
PERSONAS: tuple[Persona, ...] = (
    Persona(
        id="student",
        background=(
            "你是一名刚来纽约读研究生的中国留学生，住在皇后区，经常晚自习后"
            "坐地铁回家。你对纽约的治安传闻很敏感，中文是主要语言，预算有限，"
            "决策时很依赖手机上的信息。"
        ),
    ),
    Persona(
        id="new_immigrant",
        background=(
            "你是一个来纽约两年的新移民家庭的主妇/主夫，家里有上小学的孩子，"
            "日常要接送孩子、买菜、跑社区机构。你的英语够用但不自信，更信任"
            "中文信息，最在意社区日常安全。"
        ),
    ),
    Persona(
        id="visitor",
        background=(
            "你是一个第一次来纽约旅游的中文访客，计划逛曼哈顿中城和法拉盛，"
            "行程紧凑、靠手机导航。你对当地完全不熟，出发前想快速判断各个"
            "区域晚上能不能去。"
        ),
    ),
)


def load_interview_script(cfg: config_loader.AppConfig) -> InterviewScript:
    """加载访谈脚本草稿（配置路径，相对项目根）；题号唯一、题面非空，否则明确失败。"""
    path = Path(cfg.synthetic_user.interview_script)
    if not path.is_absolute():
        path = config_loader.PROJECT_ROOT / path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"访谈脚本不可读/不是合法 JSON：{path}（{exc}）") from exc
    version = str(raw.get("version", "")).strip()
    if not version:
        raise RuntimeError(f"访谈脚本缺少 version：{path}")
    questions_raw = raw.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        raise RuntimeError(f"访谈脚本 questions 必须是非空列表：{path}")
    questions = tuple(
        InterviewQuestion(id=str(q["id"]), question=str(q["question"]))
        for q in questions_raw
    )
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"访谈脚本题号必须唯一：{path}")
    for q in questions:
        if not q.id.strip() or not q.question.strip():
            raise RuntimeError(f"访谈脚本题号/题面不得为空：{q!r}")
    return InterviewScript(version=version, questions=questions)


def validate_reply_length(reply: SyntheticReply, cfg: config_loader.AppConfig) -> None:
    """业务校验：单条回答字数 ≤ 配置上界（结构校验，防跑题失控）。"""
    limit = cfg.synthetic_user.reply_max_chars
    if len(reply.reply) > limit:
        raise BusinessValidationError(
            f"回答超过字数上界（{len(reply.reply)} > {limit}），请精简到 {limit} 字以内"
        )


def make_reply_length_validator(cfg: config_loader.AppConfig):
    """回答字数校验器工厂（与 output_pipeline.make_*_validator 同款惯例）。

    每次预检构造一次，不在逐题循环里重建闭包。
    """

    def _validate(reply: SyntheticReply) -> None:
        validate_reply_length(reply, cfg)

    return _validate


def _make_messages(persona: Persona, question: InterviewQuestion) -> list[dict[str, str]]:
    """persona 背景进 system 消息；题面 + JSON 输出契约进 user 消息（管线契约）。"""
    return [
        {
            "role": "system",
            "content": (
                "你正在产品访谈预检中扮演一位目标用户。请完全以这个 persona 的"
                f"身份与口吻回答，不要跳出角色，不要描述产品本身的技术实现：\n"
                f"{persona.background}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"{question.question}\n\n"
                '请仅输出一个 JSON 对象，格式为 {"reply": "你的回答"}，'
                "不要附加任何解释文字。"
            ),
        },
    ]


def run_persona(
    client: LLMClient,
    persona: Persona,
    questions: tuple[InterviewQuestion, ...],
    cfg: config_loader.AppConfig,
) -> list[dict[str, Any]]:
    """单 persona 跑完全部题目：每题走输出控制管线（解析失败/超长回灌重试）。

    返回逐题回答列表，每条已盖 dev_reference_label 标注章。
    """
    label = cfg.synthetic_user.dev_reference_label
    validators = [make_reply_length_validator(cfg)]
    answers: list[dict[str, Any]] = []
    for question in questions:
        reply: SyntheticReply = run_pipeline(
            client,
            _make_messages(persona, question),
            SyntheticReply,
            cfg,
            validators=validators,
            model=cfg.synthetic_user.model,
        )
        answers.append(
            {
                "persona_id": persona.id,
                "question_id": question.id,
                "reply": reply.reply,
                "label": label,
            }
        )
    return answers


def run_precheck(
    client: LLMClient,
    script: InterviewScript,
    cfg: config_loader.AppConfig,
) -> dict[str, Any]:
    """全部 persona × 全部题目的预检主流程，产出带标注的报告 dict。

    合法输出每题恰好一次 LLM 调用；解析失败按配置上界有限重试后明确失败
    （OutputPipelineError，不静默出半成品）。
    """
    answers: list[dict[str, Any]] = []
    for persona in PERSONAS:
        answers.extend(run_persona(client, persona, script.questions, cfg))
    label = cfg.synthetic_user.dev_reference_label
    return {
        "label": label,
        "note": (
            f"本报告由 LLM 扮演的合成用户生成，仅供开发参考（{label}），"
            "永不冒充真人证据；真人结论以票 11 访谈为准。"
        ),
        "model": cfg.synthetic_user.model,
        "script_version": script.version,
        "persona_ids": [p.id for p in PERSONAS],
        "answers": answers,
    }


def write_report(report: dict[str, Any], path: str | Path) -> Path:
    """报告落盘（JSON，UTF-8，标注已随 run_precheck 盖好在头与每条回答上）。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out
