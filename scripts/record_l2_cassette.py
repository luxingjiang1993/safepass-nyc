"""L2 judge cassette 一次性录制（issue 03 / M1 起；issue 04 / B1 两路径对照）。

真实 DashScope 调用（模型 = config eval.judge_model 锁定，temperature=0）
对 50 条金标逐条做三类判定（groundedness / hallucination / relevance）。
B1 起一次录制产出四份资产：

1. tests/cassettes/l2_skill.json——Skill 路径管线 LLM 调用（三维提取 +
   建议生成，qwen-flash 考生侧）；
2. tests/cassettes/l2_judge.json——主路径（Skill 输出）judge 判定（150 条交互）；
3. tests/cassettes/l2_judge_template.json——对照路径（模板输出）judge 判定
   （150 条交互，模板路径零管线 LLM 调用，无需 skill 侧 cassette）；
4. fixtures/eval/l2_results_v1.json——两路径逐条判定 + 主指标（Skill 覆盖
   子集）+ 对照指标 + comparison_ok（回放对账 + 票 04 README 基线）。

守卫（录坏当场失败，不把错资产交给回放）：
- 响应形态必须与金标 expect 一致（l2_runner._run_path 内建，两路径同查）；
- skill 来源必须 ⊆ 金标形态推断的 eligible 子集（24 条 new_query 安全查询），
  且覆盖数 ≥ config eval.skill_coverage_min（Skill 系统性回归即失败；
  个别条目校验耗尽降级模板属设计内路径，进模板降级 marker）。

已知限制（记录在案，非事故）：
- Skill 侧管线调用未钉 temperature=0（指纹含 kwargs，钉上须全量重录）：重录时
  建议文本与 skill cassette 交互数可能漂移，守卫只卡覆盖下界——重录后必须
  重新对账 README 数字（tests/test_readme_baselines.py 守住）。
- 两路径对照差距可能系单条 judge 噪音（如 G39 曾被判为"把证据的
  sources:["模拟数据"] 标注误读为降级/越界形态"）：重录后 comparison_ok
  若翻转，先查逐条判定再迭代，不修改 DoD。

前置：环境变量 DASHSCOPE_API_KEY（一次性真实 key；此后回放不再需要）。
用法：
    python scripts/record_l2_cassette.py            # 录制（删除旧 cassette 后重建）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # safepass 包
sys.path.insert(0, str(REPO_ROOT / "tests" / "eval"))  # l2_runner（与 pytest 同路径）

from safepass import config_loader  # noqa: E402
from safepass.llm_client import ChatResponse  # noqa: E402

import l2_runner  # noqa: E402


class DashScopeClient:
    """LLMClient 协议适配：openai SDK 走 DashScope 兼容接入点（考生/考官同款）。

    显式 http_client：本仓库 openai==1.51.2 与 httpx>=0.28 的 proxies 参数
    不兼容（venv 实测 TypeError），自建 httpx.Client 绕开 SDK 默认构造。
    """

    def __init__(self, cfg: config_loader.AppConfig):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise SystemExit(
                "缺少 DASHSCOPE_API_KEY 环境变量（一次性录制需真实 key；回放不需要）"
            )
        self._model = cfg.eval.judge_model
        self._client = OpenAI(
            api_key=api_key,
            base_url=cfg.eval.base_url,
            http_client=httpx.Client(timeout=120),
        )

    def chat(self, messages, *, model=None, **kwargs):
        # 管线调用 model=None（suggestion_skill.generate 默认），与生产接线同款
        # 解析：model or 配置模型（llm_wiring.OpenAICompatibleClient 先例）。
        # 指纹由 chat_with_cassette 在进入本客户端前以收到的 kwarg 计算，
        # 此处替换不影响录制/回放两侧指纹一致性。
        response = self._client.chat.completions.create(
            model=model or self._model, messages=list(messages), **kwargs
        )
        return ChatResponse(
            content=response.choices[0].message.content or "", model=response.model or ""
        )


def _delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()  # 全量重录：旧交互与新提示词指纹必然不匹配，不留残骸


def main() -> None:
    cfg = config_loader.load_config()
    cassettes = (
        l2_runner.cassette_path(cfg),
        l2_runner.template_judge_cassette_path(cfg),
        l2_runner.skill_cassette_path(cfg),
    )
    for cassette in cassettes:
        _delete_if_exists(cassette)

    client = DashScopeClient(cfg)
    results = l2_runner.run_l2_suite(judge_client=client, cfg=cfg, record=True)

    l2_runner.write_results(results)
    print("cassettes 落盘：")
    for cassette in cassettes:
        print(f"  {cassette.relative_to(REPO_ROOT)}")
    print(f"结果工件：{l2_runner.RESULTS_PATH.relative_to(REPO_ROOT)}")

    main_metrics = results["metrics"]
    template_metrics = results["template_path"]["metrics"]
    print(
        "主指标（Skill 路径，Skill 覆盖子集 {n_entries} 条）："
        "groundedness_mean={groundedness_mean:.3f} "
        "relevance_mean={relevance_mean:.3f} hallucination_rate={hallucination_rate:.3f}".format(
            **main_metrics
        )
    )
    print(
        "对照指标（模板路径，同 {n_entries} 条）："
        "groundedness_mean={groundedness_mean:.3f} "
        "relevance_mean={relevance_mean:.3f} hallucination_rate={hallucination_rate:.3f}".format(
            **template_metrics
        )
    )
    fallback = results["metrics_template_fallback"]
    print(
        "模板降级 marker（{n_entries} 条，不计入主 groundedness）："
        "groundedness_mean={groundedness_mean:.3f} "
        "hallucination_rate={hallucination_rate:.3f}".format(**fallback)
    )
    ok = results["comparison"]["comparison_ok"]
    print(f"收口条件（Skill ≥ 模板，hallucination 取 ≤）：{ok}")
    if not all(ok.values()):
        print("!!! 主指标未跑赢模板对照：按 B1 定案迭代到打得过再收（不修改 DoD）")
        sys.exit(1)  # 与守卫姿态一致：收口未达成 = 录制任务失败，交回人工迭代


if __name__ == "__main__":
    main()
