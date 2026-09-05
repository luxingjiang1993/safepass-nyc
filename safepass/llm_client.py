"""LLM 客户端注入点与录制回放（cassette）基建（issue 01 / RALPH.md「运行」章节）。

模型调用一律经可注入参数传入接缝，不在模块内硬编码客户端：

- ``LLMClient`` 协议：任何实现 ``chat(messages, *, model=None, **kwargs)``
  的对象都可注入——生产环境包装真实 SDK，测试注入 fake/stub。
- ``chat_with_cassette``：录制回放。录制阶段（一次性、在线）把
  请求指纹 + 响应写入 JSON cassette；此后离线重放，顺序与指纹严格匹配，
  保证测试可重复且不进真实 API。

cassette 是测试资产，存于 tests/cassettes/，不入生产路径。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence


class LLMClient(Protocol):
    """可注入的 LLM 客户端协议。生产实现包装模型 SDK；测试注入 fake/stub。"""

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> "ChatResponse": ...


@dataclass(frozen=True)
class ChatResponse:
    """一次模型调用的最小确定性响应（结构化输出走 content 承载 JSON 文本）。"""

    content: str
    model: str = ""


class CassetteError(RuntimeError):
    """回放失败：cassette 缺失、耗尽或请求指纹与录制不符（明确失败，不静默）。"""


def _fingerprint(messages: Sequence[dict[str, Any]], kwargs: dict[str, Any]) -> str:
    payload = json.dumps(
        {"messages": list(messages), "kwargs": kwargs},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 每个 cassette 文件已消费的交互数（进程内，保证同一次测试中严格按序消费）
_consumed: dict[Path, int] = {}


def reset_cassette_cursor(cassette_path: str | Path) -> None:
    """测试夹具用：让指定 cassette 从头开始回放。"""
    _consumed.pop(Path(cassette_path), None)


def chat_with_cassette(
    client: LLMClient,
    cassette_path: str | Path,
    messages: Sequence[dict[str, Any]],
    *,
    model: str | None = None,
    record: bool = False,
    **kwargs: Any,
) -> ChatResponse:
    """cassette 存在则离线重放；否则调用 client 并把交互录制到 cassette。

    重放是严格的：下一条录制交互的请求指纹必须与本次调用一致，
    否则抛 CassetteError（防止测试改了提示词却还在用旧录制 silently 通过）。

    record=True 显式切录制模式（一次性在线，如 scripts/record_l2_cassette.py）：
    一律追加新交互并推进游标，绝不回放——同一进程连续录制多条交互
    （L2 套件 50 条 × 3 判定 = 150 条）不会因为游标语义混用而失败。
    回放路径绝不使用 record=True（耗尽/指纹不符必须报错，不静默补录）。
    """
    path = Path(cassette_path)
    fp = _fingerprint(messages, {"model": model, **kwargs})

    if not record and path.exists():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))["interactions"]
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            raise CassetteError(f"cassette 损坏：{path}（{exc}）") from exc
        idx = _consumed.get(path, 0)
        if idx >= len(entries):
            raise CassetteError(
                f"cassette 已耗尽：{path} 共 {len(entries)} 条交互，"
                f"第 {idx + 1} 次调用无录制可用（需重新录制）"
            )
        entry = entries[idx]
        _consumed[path] = idx + 1
        if entry.get("fingerprint") != fp:
            raise CassetteError(
                f"cassette 指纹不匹配：{path} 第 {idx + 1} 条交互的请求与本次调用不同，"
                "测试或提示词已变更，需重新录制"
            )
        return ChatResponse(**entry["response"])

    # 录制分支（一次性、在线）：调用真实/fake 客户端并落盘
    response = client.chat(messages, model=model, **kwargs)
    if not isinstance(response, ChatResponse):
        response = ChatResponse(content=str(response), model=model or "")
    entries: list[dict[str, Any]] = []
    if path.exists():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))["interactions"]
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            raise CassetteError(f"cassette 损坏：{path}（{exc}）") from exc
    entries.append({"fingerprint": fp, "response": asdict(response)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"interactions": entries}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    # 录制也把消费游标推进到最新条目：同一进程内连续录制多条交互
    # （如 L2 套件 50 条 × 3 判定）时，下一条调用不会误回放已录制的首条。
    _consumed[path] = len(entries)
    return response
