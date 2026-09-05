"""票 13 验收测试：Dockerfile + 冒烟的部署产物静态校验（spec v2「部署」节）。

对应 .scratch/safepass-phase2-tickets/issues/13-docker-smoke.md 三条勾选：
    1. docker build 成功、单容器跑起应用 —— 真机验收属人工出口标准
       （spec Testing Decisions：不进 pytest），此处静态锁死构建产物的
       关键结构与一致性，真机冒烟走 scripts/docker_smoke.sh
    2. 冒烟脚本通过（首页 200、查询页可达）—— 脚本存在性、路由与端口
       一致性进本文件；真实容器内通过是人工出口
    3. Dockerfile 关键指令静态校验 —— 本文件主体

解析方式是逐行扫描（不引第三方 Dockerfile parser，Karpathy 宪法：
标准库能解决的绝不引依赖）；按 `FROM` 切阶段，runtime 专属断言只看
最后一个阶段段。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "docker_smoke.sh"
SERVE_ENTRY = REPO_ROOT / "scripts" / "serve.py"


def _stages() -> list[tuple[str, list[str]]]:
    """把 Dockerfile 按 FROM 切成 [(stage_name, 行列表), ...]。"""
    assert DOCKERFILE.exists(), "缺少 Dockerfile（票 13 交付物）"
    text = DOCKERFILE.read_text(encoding="utf-8")
    stages: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^FROM\s+\S+\s+AS\s+(\S+)", line)
        if m:
            if current_name is not None:
                stages.append((current_name, current_lines))
            current_name = m.group(1)
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)
    if current_name is not None:
        stages.append((current_name, current_lines))
    return stages


def _runtime_stage() -> tuple[str, list[str]]:
    stages = _stages()
    assert stages, "Dockerfile 没有任何 FROM 阶段"
    return stages[-1]


# ---------------------------------------------------------------------------
# 1. 多阶段结构：deps → index → runtime（spec v2「容器化」节的固定形态）
# ---------------------------------------------------------------------------


def test_multistage_deps_index_runtime():
    names = [name for name, _ in _stages()]
    assert len(names) >= 3, f"多阶段要求 ≥3 个 FROM，实际：{names}"
    assert names[:3] == ["deps", "index", "runtime"], (
        f"阶段顺序须为 deps → index → runtime（spec v2），实际：{names}"
    )


# ---------------------------------------------------------------------------
# 2. 基镜像钉版（禁 latest / 无 tag，防止构建随上游漂移）
# ---------------------------------------------------------------------------


def test_base_images_pinned_no_latest():
    text = DOCKERFILE.read_text(encoding="utf-8")
    stage_names = {name for name, _ in _stages()}
    for line in text.splitlines():
        if not line.startswith("FROM "):
            continue
        image = line.split()[1]
        if image in stage_names:
            continue  # 阶段链引用（FROM deps AS index），基镜像已在链首钉版
        assert image != "scratch"
        assert ":" in image and not image.endswith(":latest"), (
            f"基镜像必须钉版（禁 latest）：{line}"
        )


# ---------------------------------------------------------------------------
# 3. 索引构建阶段：构建即自检（--check 重建比对，确定性验收）
# ---------------------------------------------------------------------------


def test_index_build_stage_self_checks():
    index_lines = dict(_stages())["index"]
    run_lines = [l.strip() for l in index_lines if l.strip().startswith("RUN ")]
    assert any("scripts/build_index.py --check" in l for l in run_lines), (
        "index 阶段必须用 build_index.py --check 构建并自检索引"
    )


# ---------------------------------------------------------------------------
# 4. runtime 阶段：离线运行（模型缓存随层拷贝 + 强制离线 env）
# ---------------------------------------------------------------------------


def test_runtime_forced_offline_with_model_cache():
    _, lines = _runtime_stage()
    joined = "\n".join(lines)
    assert "HF_HUB_OFFLINE=1" in joined, "runtime 必须强制 HF 离线"
    assert "TRANSFORMERS_OFFLINE=1" in joined, "runtime 必须强制 transformers 离线"
    cache_copies = [
        l for l in lines if l.strip().startswith("COPY --from=index") and "huggingface" in l
    ]
    assert cache_copies, (
        "runtime 必须从 index 阶段拷贝 huggingface 模型缓存（查询向量编码离线可跑）"
    )


def test_runtime_non_root_user():
    _, lines = _runtime_stage()
    user_lines = [l.strip() for l in lines if l.strip().startswith("USER ")]
    assert user_lines, "runtime 必须以非 root 用户运行（USER 指令）"
    assert all("root" not in l.split()[1] for l in user_lines), (
        f"USER 不得为 root：{user_lines}"
    )


# ---------------------------------------------------------------------------
# 5. 端口一致性：EXPOSE == serve.py 默认 PORT == 冒烟脚本容器侧端口
# ---------------------------------------------------------------------------


def _exposed_port() -> str:
    _, lines = _runtime_stage()
    expose = [l.strip() for l in lines if l.strip().startswith("EXPOSE ")]
    assert len(expose) == 1, f"EXPOSE 恰好一条，实际：{expose}"
    return expose[0].split()[1]


def _serve_default_port() -> str:
    text = SERVE_ENTRY.read_text(encoding="utf-8")
    m = re.search(r"^PORT\s*=\s*(\d+)", text, re.M)
    assert m, "serve.py 必须固定 PORT 常量（与 EXPOSE/HEALTHCHECK 一致）"
    return m.group(1)


def test_port_consistency_expose_serve_smoke():
    exposed = _exposed_port()
    assert exposed == _serve_default_port(), (
        f"EXPOSE({exposed}) 与 serve.py 默认 PORT 不一致"
    )
    smoke = SMOKE_SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"\$\{PORT\}:(\d+)", smoke)
    assert m, "冒烟脚本的端口映射须以容器侧固定端口结尾（${PORT}:<port>）"
    assert m.group(1) == exposed, (
        f"冒烟脚本容器侧端口({m.group(1)}) 与 EXPOSE({exposed}) 不一致"
    )


def test_healthcheck_hits_exposed_port():
    _, lines = _runtime_stage()
    joined = "\n".join(lines)
    assert f"127.0.0.1:{_exposed_port()}/" in joined, (
        "HEALTHCHECK 必须探测 EXPOSE 端口的首页"
    )


def test_hf_home_matches_model_cache_copy_target():
    """离线运行全靠本机缓存：HF_HOME 必须等于模型缓存的 COPY 目标，
    任一侧路径漂移都是"构建过、运行时首轮查询静默炸"（端口一致性同款锁）。"""
    _, lines = _runtime_stage()
    joined = "\n".join(lines)
    m = re.search(r"HF_HOME=(\S+)", joined)
    assert m, "runtime 必须显式设置 HF_HOME（本机模型缓存位置）"
    hf_home = m.group(1)
    cache_copies = [
        l.strip()
        for l in lines
        if l.strip().startswith("COPY --from=index") and "huggingface" in l
    ]
    assert cache_copies, "缺少从 index 阶段拷贝模型缓存的指令"
    target = cache_copies[0].split()[-1]
    assert target == hf_home, (
        f"HF_HOME({hf_home}) 与模型缓存 COPY 目标({target}) 不一致"
    )


# ---------------------------------------------------------------------------
# 6. runtime 拷贝的运行时资产必须真实存在于仓库（COPY 不悬空）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "asset",
    ["safepass", "frontend", "scripts", "config", "fixtures"],
)
def test_runtime_copy_sources_exist(asset):
    assert (REPO_ROOT / asset).exists(), f"runtime COPY 的 {asset} 在仓库中不存在"
    _, lines = _runtime_stage()
    copies = [l.strip() for l in lines if l.strip().startswith("COPY ")]
    assert any(re.search(rf"^COPY {re.escape(asset)}\s", l) for l in copies), (
        f"runtime 阶段缺少对 {asset} 的 COPY"
    )


def test_deps_stage_copies_requirements():
    deps_lines = dict(_stages())["deps"]
    copies = [l.strip() for l in deps_lines if l.strip().startswith("COPY ")]
    assert any(l == "COPY requirements.txt ./" for l in copies), (
        "deps 阶段必须 COPY requirements.txt（依赖单一事实源）"
    )


def test_runtime_uses_real_dataset():
    """生产镜像必须带真实 NYPD 数据集（config runtime_dataset_path 指向）。"""
    from safepass import config_loader

    cfg = config_loader.get_config()
    dataset = REPO_ROOT / cfg.data_source.runtime_dataset_path
    assert dataset.exists(), f"生产数据集缺失：{dataset}"
    _, lines = _runtime_stage()
    assert any(l.strip().startswith("COPY fixtures ") for l in lines), (
        "runtime 必须 COPY fixtures（含真实数据集与检索索引）"
    )


# ---------------------------------------------------------------------------
# 7. 运行入口：CMD 指向 scripts.serve（绑 0.0.0.0）
# ---------------------------------------------------------------------------


def test_cmd_runs_serve_entrypoint():
    _, lines = _runtime_stage()
    # 只认顶格 CMD（HEALTHCHECK 的探测命令是缩进续行，不算入口指令）
    cmd = [l.strip() for l in lines if l.startswith("CMD ")]
    assert len(cmd) == 1, f"CMD 恰好一条，实际：{cmd}"
    assert "scripts.serve" in cmd[0], "CMD 必须运行 scripts.serve（容器入口）"
    serve_text = SERVE_ENTRY.read_text(encoding="utf-8")
    assert '"0.0.0.0"' in serve_text, "serve.py 默认必须绑 0.0.0.0（容器对外监听）"


# ---------------------------------------------------------------------------
# 8. .dockerignore：密钥、课程材料、测试世界永不进镜像
# ---------------------------------------------------------------------------


def test_dockerignore_excludes_secrets_and_test_world():
    assert DOCKERIGNORE.exists(), "缺少 .dockerignore"
    patterns = {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for required in (
        ".env",
        ".venv/",
        ".git/",
        "可用来参考的代码案例/",
        "tests/",
    ):
        assert required in patterns, f".dockerignore 缺少排除项：{required}"


# ---------------------------------------------------------------------------
# 9. 冒烟脚本：build → run → 首页 200 → 查询页 200 的结构存在
# ---------------------------------------------------------------------------


def test_smoke_script_present_and_structured():
    assert SMOKE_SCRIPT.exists(), "缺少 scripts/docker_smoke.sh（票 13 交付物）"
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "docker build" in script, "冒烟脚本必须 docker build"
    assert "docker run" in script, "冒烟脚本必须 docker run"
    assert re.search(r'/\?q=|/query', script) or "data-urlencode" in script, (
        "冒烟脚本必须覆盖查询页"
    )
    assert script.count('"200"') >= 2, "首页与查询页各须断言一次 200"
    assert "docker rm -f" in script, "冒烟脚本必须清理容器（含 trap 兜底）"
