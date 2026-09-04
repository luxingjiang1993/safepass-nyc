"""会话状态（spec D2/D6；issue 08 / RALPH T6 落地载体）。

持有上轮查询的**结构化结果**（地点、评级、数据摘要），是追问（spec D6 /
F8）的上下文载体；不存完整对话历史。仅存在于当前会话：本模块是纯数据
定义，零 I/O、零持久化、零上传，随页面关闭销毁（追问流程的落盘防线由
tests/test_followup.py 的接缝级 mtime 断言守护）。

承接规则（from_result）：
    SafetyQueryResult  → 单区域快照；
    ComparisonResult   → 各区域快照，last = 用户最后聚焦的区域
                         （对比追问列表顺序的末位，确定性可复算）；
    Degraded/Emergency → 不含可承接的结构化区域结果，抛 TypeError 明确失败，
                         调用方据此清空会话状态，绝不产出伪承接。
换地点、换话题即视为新查询：调用方以新响应重建会话状态（管线本身无状态）。
"""

from __future__ import annotations

from dataclasses import dataclass

from safepass import contracts


@dataclass(frozen=True)
class AreaSnapshot:
    """单区域的结构化摘要：地点 + 评级 + 数据摘要（sample_size）。"""

    area: str
    precinct: int
    rating: str
    sample_size: int


@dataclass(frozen=True)
class SessionState:
    """上轮结构化结果载体（spec D2/D6）。字段集即"不存对话历史"的结构防线。"""

    last: AreaSnapshot
    areas: tuple[AreaSnapshot, ...]

    @classmethod
    def from_result(cls, result: contracts.ResponseContract) -> "SessionState":
        """从响应契约提取结构化摘要；降级/紧急形态不含区域结果 → TypeError。"""
        if isinstance(result, contracts.SafetyQueryResult):
            snap = AreaSnapshot(
                area=result.area,
                precinct=result.precinct,
                rating=result.rating,
                sample_size=result.sample_size,
            )
            return cls(last=snap, areas=(snap,))
        if isinstance(result, contracts.ComparisonResult) and result.areas:
            snaps = tuple(
                AreaSnapshot(
                    area=a.area,
                    precinct=a.precinct,
                    rating=a.rating,
                    sample_size=a.sample_size,
                )
                for a in result.areas
            )
            return cls(last=snaps[-1], areas=snaps)
        raise TypeError(
            f"响应形态 {type(result).__name__} 不含可承接的结构化区域结果，"
            "不得据此构建会话状态（降级/紧急响应应清空会话状态）"
        )
