"""A1 一次性追加录制：给既有接缝 cassette 追加第 3 条交互（建议 Skill 调用）。

测试世界 = mock 数据集（tests/conftest.py 同款钉子）。第 1-2 次调用直接按
既有 cassette 条目回放（指纹不变、条目不动），第 3 次（建议 Skill）经
chat_with_cassette(record=True) 追加录制——响应为剧本 fake 的合法样例
（离线构造；A2 注入检索时再用真实模型重录）。运行：
    PYTHONIOENCODING=utf-8 python .scratch/record_a1_skill_entries.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from safepass import data_agent
from safepass.llm_client import ChatResponse, chat_with_cassette
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ[data_agent.DATASET_PATH_ENV] = str(REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv")

SEAM_CASSETTE = REPO_ROOT / "tests" / "cassettes" / "fc_routing_seam.json"
EXTRACTION_CASSETTE = REPO_ROOT / "tests" / "cassettes" / "extraction_ac002.json"

# 建议 Skill 的剧本响应（数据定调：与 mock 世界聚合数字一致，grounds 空 = A1 现状）
SEAM_SKILL_OUT = json.dumps(
    {
        "suggestions": [
            "夜间出行优先选择照明好、人流多的主干道，避开偏僻小巷",
            "随身包放在身前视线范围内，手机不要边走边外露",
            "本区夜间案件少于白天，22 点后仍建议尽量结伴通行",
        ],
        "suggestion_grounds": [],
    },
    ensure_ascii=False,
)
EXTRACTION_SKILL_OUT = json.dumps(
    {
        "suggestions": [
            "晚上 10 点从图书馆回家，优先走照明好的主干道",
            "把包放在身前、手机拿在手里，避免边走路边看手机",
            "提前把行程告诉朋友，到家后报个平安",
        ],
        "suggestion_grounds": [],
    },
    ensure_ascii=False,
)


class _Inner:
    """录制模式下的底层客户端：返回建议 Skill 的剧本响应。"""

    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, messages, *, model=None, **kwargs):
        return ChatResponse(content=self._content, model="scripted")


class _AppendThird:
    """第 1-2 次按既有 cassette 条目回放，第 3 次（建议 Skill）追加录制。"""

    def __init__(self, path: Path, script: list[str], skill_out: str) -> None:
        self._path = path
        self._script = list(script)
        self._inner = _Inner(skill_out)
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        if self.calls == 3:
            return chat_with_cassette(
                self._inner, self._path, messages, model=model, record=True, **kwargs
            )
        return ChatResponse(content=self._script.pop(0), model="scripted")


def _entry_contents(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [e["response"]["content"] for e in data["interactions"]]


def main() -> None:
    seam_script = _entry_contents(SEAM_CASSETTE)
    client = _AppendThird(SEAM_CASSETTE, seam_script, SEAM_SKILL_OUT)
    result = execute_query("上东区晚上安全吗？", llm_client=client)
    assert result.type == "safety" and client.calls == 3, (result.type, client.calls)
    print("seam ok:", result.suggestions_source, len(result.suggestions))

    extraction_script = _entry_contents(EXTRACTION_CASSETTE)
    client2 = _AppendThird(EXTRACTION_CASSETTE, extraction_script, EXTRACTION_SKILL_OUT)
    result2 = execute_query(
        "我是女生，晚上10点从图书馆回家，Upper East Side安全吗？", llm_client=client2
    )
    assert result2.type == "safety" and client2.calls == 3, (result2.type, client2.calls)
    print("extraction ok:", result2.suggestions_source, len(result2.suggestions))


if __name__ == "__main__":
    main()
