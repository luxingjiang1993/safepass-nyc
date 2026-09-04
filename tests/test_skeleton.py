"""issue 01 验收测试：工程骨架与接缝空壳。

对应 .scratch/safepass-nyc-mvp/issues/01-engineering-skeleton-and-seam.md 四条勾选：
    1. pytest 布局就绪，`pytest tests/ -q` 可跑通（本文件即首批测试）
    2. 集中配置承载阈值/样本量档位/覆盖警区/全市均值；产品代码零散落字面量
    3. LLM 调用经可注入参数传入接缝；fake/stub 与 cassette 回放可用
    4. execute_query 空壳存在，调用抛出明确"未实现"错误
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from safepass import config_loader
from safepass.llm_client import (
    CassetteError,
    ChatResponse,
    chat_with_cassette,
    reset_cassette_cursor,
)
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "safepass"

# ---------------------------------------------------------------------------
 # 1. pytest 布局与包可导入
# ---------------------------------------------------------------------------


def test_package_importable_and_modules_present():
    for mod in (
        "contracts",
        "config_loader",
        "llm_client",
        "session_state",
        "emergency",
        "routing",
        "data_agent",
        "rating_engine",
        "intel_agent",
        "output_pipeline",
        "pipeline",
    ):
        assert (PACKAGE_DIR / f"{mod}.py").exists(), f"缺少模块 safepass/{mod}.py"
    import safepass  # noqa: F401


# ---------------------------------------------------------------------------
# 2. 集中配置（spec D4）
# ---------------------------------------------------------------------------


def test_config_thresholds_and_tiers_loaded_from_yaml():
    cfg = config_loader.load_config()
    # 阈值系数来自 config/app.yaml，不是代码字面量
    assert cfg.thresholds.green_max_ratio == pytest.approx(0.7)
    assert cfg.thresholds.red_min_ratio == pytest.approx(1.3)

    # 样本量四档：0-9 强制 insufficient_data；10-29 LOW；30-99 MODERATE；>=100 HIGH
    tiers = {t.min: t for t in cfg.sample_size_tiers}
    assert [t.min for t in cfg.sample_size_tiers] == [0, 10, 30, 100]
    assert tiers[0].max == 9 and tiers[0].rating == "insufficient_data"
    assert tiers[0].confidence is None
    assert tiers[10].max == 29 and tiers[10].confidence == "LOW"
    assert tiers[30].max == 99 and tiers[30].confidence == "MODERATE"
    assert tiers[100].max is None and tiers[100].confidence == "HIGH"
    for t in cfg.sample_size_tiers:
        assert t.rating in (None, "insufficient_data"), "评级只允许枚举值"


def test_config_coverage_precincts_and_city_mean():
    cfg = config_loader.load_config()
    # 覆盖警区清单（CONTEXT.md：19 上东区 / 109 法拉盛 / 5 唐人街 / 90 威廉斯堡 / 84 布鲁克林高地）
    assert cfg.covered_precincts == frozenset({19, 109, 5, 90, 84})
    # 中城 14/18 明确不在覆盖内（spec D4）
    assert cfg.excluded_precincts == frozenset({14, 18})
    assert not (cfg.covered_precincts & cfg.excluded_precincts)
    # 全市均值键存在；T0 fixture 生成后填入具体值（此前为 None 是合法状态）
    assert "city_mean_per_100k" in repr(cfg) or cfg.city_mean_per_100k is None or cfg.city_mean_per_100k > 0
    assert cfg.max_retries >= 0
    # 可信度解释模板带 {n} 占位（动态真实命中数）
    for text in cfg.confidence_explanations.values():
        assert "{n}" in text


def test_config_loader_honours_explicit_path_and_validates(tmp_path):
    custom = tmp_path / "app.yaml"
    custom.write_text(
        re.sub(
            r"city_mean_per_100k:\s*\S+",
            "city_mean_per_100k: 1234.5",
            (REPO_ROOT / "config" / "app.yaml").read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    cfg = config_loader.load_config(custom)
    assert cfg.city_mean_per_100k == pytest.approx(1234.5)

    broken = tmp_path / "broken.yaml"
    broken.write_text("rating: {}\n", encoding="utf-8")
    with pytest.raises(config_loader.ConfigError):
        config_loader.load_config(broken)

    with pytest.raises(config_loader.ConfigError):
        config_loader.load_config(tmp_path / "missing.yaml")


# ---------------------------------------------------------------------------
# 3. 零散落字面量 grep 审查（扫描产品代码 safepass/，配置与测试除外）
# ---------------------------------------------------------------------------


def _product_python_files() -> list[Path]:
    return sorted(
        p for p in PACKAGE_DIR.rglob("*.py") if p.is_file()
    )


def test_no_scattered_threshold_literals_in_product_code():
    offenders = []
    for path in _product_python_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if re.search(r"(?<![\w.])0\.7(?![\w.])", line) or re.search(
                r"(?<![\w.])1\.3(?![\w.])", line
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "阈值系数散落在产品代码中（应只存在于 config/app.yaml）：\n" + "\n".join(offenders)


def test_no_scattered_precinct_list_in_product_code():
    offenders = []
    # 覆盖警区清单整体出现（任意常见书写形态）即违规；单个小数字不查（误报太高）
    list_pattern = re.compile(
        r"\[?\s*\b19\b\s*,\s*\b109\b\s*,\s*\b5\b\s*,\s*\b90\b\s*,\s*\b84\b\s*\]?"
    )
    for path in _product_python_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if list_pattern.search(line) or re.search(r"\b109\b", line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "覆盖警区清单散落在产品代码中（应只存在于 config/app.yaml）：\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# 4. LLM 注入点与 cassette 回放
# ---------------------------------------------------------------------------


class _FakeLLM:
    """测试 fake：计数调用，按消息内容返回固定响应。"""

    def __init__(self, content: str = '{"ok": true}'):
        self.calls = 0
        self._content = content

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(content=self._content, model=model or "fake")


def test_llm_client_injectable_via_seam_signature():
    # 接缝接受 llm_client 注入参数（fake 可满足协议，无需真实 SDK）
    fake = _FakeLLM(content='{"route": "area_safety_query"}')
    import inspect

    sig = inspect.signature(execute_query)
    assert "llm_client" in sig.parameters
    # issue 05（T3）起接缝已填入最小实现：注入 fake 经路由层产出结构化契约
    result = execute_query("上东区晚上安全吗？", llm_client=fake)
    assert getattr(result, "type", None) in ("safety", "comparison", "degraded")
    assert fake.calls >= 1, "路由层应真实消费注入的 llm_client"


def test_cassette_record_then_replay_offline(tmp_path):
    cassette = tmp_path / "test_cassette.json"
    fake = _FakeLLM(content='{"route": "area_safety_query"}')

    # 第一遍：录制（走真实/fake 客户端）
    resp1 = chat_with_cassette(
        fake, cassette, [{"role": "user", "content": "上东区安全吗"}], model="m"
    )
    assert resp1.content == '{"route": "area_safety_query"}'
    assert fake.calls == 1
    assert cassette.exists()

    # 第二遍：新 fake + 回放——客户端调用计数必须为 0（纯离线）
    fake2 = _FakeLLM()
    reset_cassette_cursor(cassette)
    resp2 = chat_with_cassette(
        fake2, cassette, [{"role": "user", "content": "上东区安全吗"}], model="m"
    )
    assert resp2 == resp1
    assert fake2.calls == 0, "回放不应触发任何真实 LLM 调用"


def test_cassette_is_deterministic_byte_identical(tmp_path):
    cassette_a = tmp_path / "a.json"
    cassette_b = tmp_path / "b.json"
    for target in (cassette_a, cassette_b):
        chat_with_cassette(
            _FakeLLM(), target, [{"role": "user", "content": "同一条请求"}], model="m"
        )
    assert cassette_a.read_bytes() == cassette_b.read_bytes()
    data = json.loads(cassette_a.read_text(encoding="utf-8"))
    assert len(data["interactions"]) == 1
    assert data["interactions"][0]["fingerprint"]


def test_cassette_strict_replay_mismatch_and_exhaustion(tmp_path):
    cassette = tmp_path / "strict.json"
    chat_with_cassette(_FakeLLM(), cassette, [{"role": "user", "content": "原请求"}], model="m")

    # 请求变了：指纹不匹配 → 明确失败（防止旧录制 silently 通过新测试）
    reset_cassette_cursor(cassette)
    with pytest.raises(CassetteError):
        chat_with_cassette(_FakeLLM(), cassette, [{"role": "user", "content": "改过的请求"}], model="m")

    # 耗尽：只有 1 条录制，第 2 次调用 → 明确失败
    reset_cassette_cursor(cassette)
    chat_with_cassette(_FakeLLM(), cassette, [{"role": "user", "content": "原请求"}], model="m")
    with pytest.raises(CassetteError):
        chat_with_cassette(_FakeLLM(), cassette, [{"role": "user", "content": "原请求"}], model="m")


# ---------------------------------------------------------------------------
# 5. 接缝空壳（issue 01 第 4 条）——已由 issue 05 / T3 填入最小实现
# ---------------------------------------------------------------------------


def test_seam_returns_structured_contract_not_stub():
    """issue 01 的空壳约定（调用即抛 NotImplementedError）已由 T3 最小实现取代：
    覆盖区内查询产出 SafetyQueryResult 结构化契约，评级为合法枚举。"""
    result = execute_query("上东区晚上安全吗", profile={"crowd": "女性"}, session_state=None)
    assert result.type == "safety"
    assert result.rating in ("green", "yellow", "red", "insufficient_data")
    assert result.disclaimer, "免责声明每处存在（横切字段）"
