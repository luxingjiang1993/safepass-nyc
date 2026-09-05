"""合成用户预检一次性运行脚本（票 10 / M3，spec v2「合成用户」节）。

真实 DashScope 调用（模型/接入点 = config synthetic_user 节锁定，dev 路由
Qwen）让 LLM 扮演三类目标用户 persona，逐题预戳访谈脚本草稿，预检报告
落盘 docs/user-research/synthetic_precheck_v1.json（配置 output_path，
与 fixtures/ 测试资产隔离，永不混入金标数据目录）。

前置（人工一次性）：环境变量 DASHSCOPE_API_KEY。缺失时明确失败（非零退出 +
提示），不静默。全部产出带"开发参考"标注——合成用户永不冒充真人证据。

用法：
    python scripts/run_synthetic_precheck.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # safepass 包

from safepass import config_loader, synthetic_user  # noqa: E402
from safepass.llm_client import ChatResponse  # noqa: E402


class DashScopeSyntheticUser:
    """LLMClient 协议适配：openai SDK 走 DashScope 兼容接入点。

    显式 http_client：本仓库 openai==1.51.2 与 httpx>=0.28 的 proxies 参数
    不兼容（venv 实测 TypeError），自建 httpx.Client 绕开 SDK 默认构造
    （scripts/record_l2_cassette.py 同款先例）。key 守卫在构造函数
    （与 record_l2_cassette.py 的 DashScopeJudge 同款，同职脚本同一位置）。
    """

    def __init__(self, cfg: config_loader.AppConfig):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise SystemExit(
                "缺少 DASHSCOPE_API_KEY 环境变量（一次性真实 key；预检非测试路径，"
                "测试走 fake 离线，不需要 key）"
            )
        self._model = cfg.synthetic_user.model
        self._client = OpenAI(
            api_key=api_key,
            base_url=cfg.synthetic_user.base_url,
            http_client=httpx.Client(timeout=cfg.llm.request_timeout_seconds),
        )

    def chat(self, messages, *, model=None, **kwargs):
        response = self._client.chat.completions.create(
            model=model or self._model, messages=list(messages), **kwargs
        )
        return ChatResponse(
            content=response.choices[0].message.content or "", model=response.model or ""
        )


def main() -> None:
    cfg = config_loader.load_config()
    script = synthetic_user.load_interview_script(cfg)
    client = DashScopeSyntheticUser(cfg)
    report = synthetic_user.run_precheck(client, script, cfg)

    out = Path(cfg.synthetic_user.output_path)
    if not out.is_absolute():
        out = REPO_ROOT / out
    synthetic_user.write_report(report, out)
    print(f"预检报告落盘：{out.relative_to(REPO_ROOT)}")
    print(
        f"persona={len(report['persona_ids'])} 题={len(script.questions)} "
        f"回答={len(report['answers'])} 标注={report['label']}（永不冒充真人证据）"
    )


if __name__ == "__main__":
    main()
