# syntax=docker/dockerfile:1
# ============================================================================
# SafePass NYC — 单一 Dockerfile（票 13 / M4，spec v2「容器化」节）
#
# 多阶段：deps（依赖）→ index（检索索引构建）→ runtime（全应用单容器）。
# 与零服务架构故事一致：全应用一个容器，运行期零外部服务依赖
# （数据 = fixtures/nypd_real 真实 NYPD 数据集 + fixtures/index 检索索引，
#  全部文件形态，随镜像分发）。
#
# 运行入口 scripts/serve.py（绑 0.0.0.0，与 EXPOSE/HEALTHCHECK 端口一致）；
# 冒烟验收 scripts/docker_smoke.sh；静态校验 tests/test_dockerfile.py。
# 生产 LLM 接线（env 注入 DeepSeek 客户端，spec v2「生产模型接线」节）属票 12，
# 接线时在此追加 ENV 即可——本文件已为其留好单一层，无需重组。
# ============================================================================

# ---------- Stage 1: deps — 依赖层（requirements 不变则整层缓存命中） ----------
FROM python:3.12-slim AS deps

# libgomp1：faiss-cpu / torch 的运行时 OpenMP 依赖（slim 基础镜像不含）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 先装 CPU 版 torch（默认索引的 torch 拉 ~2.5GB CUDA 依赖，运行时纯 CPU
# 用不到；CPU wheel ~200MB）。requirements.txt 仍是应用依赖的单一事实源，
# 此行只是安装源的层内优化——sentence-transformers 的 torch 依赖已被满足。
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Stage 2: index — 检索索引构建 + embedding 模型落缓存 ----------
FROM deps AS index

# 构建期允许联网：下载本地 embedding 模型（sentence-transformers）。
# build_index.py 的 HF_HUB_OFFLINE setdefault 不覆盖显式 ENV（"0" 视为在线）；
# runtime 阶段强制离线（模型缓存已随层拷贝，运行期零网络依赖）。
ENV HF_HUB_OFFLINE=0 \
    TRANSFORMERS_OFFLINE=0
COPY fixtures/knowledge ./fixtures/knowledge
COPY scripts/__init__.py ./scripts/__init__.py
COPY scripts/build_index.py ./scripts/build_index.py
# --check：重建到内存并与落盘索引比对（确定性自检，构建即验收索引产物）
RUN python scripts/build_index.py --check

# ---------- Stage 3: runtime — 全应用运行时 ----------
FROM python:3.12-slim AS runtime

# libgomp1 同上（runtime 是独立基础镜像，系统库不经 deps 层继承）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # 运行时强制离线：embedding 模型来自下方随层拷贝的本地缓存，
    # 查询向量编码零网络依赖（Karpathy 宪法：能复现才算完成）
    HF_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
WORKDIR /app

# 依赖：从 deps 层拷贝已安装 site-packages（同基础镜像，不经 pip 重装）
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
# embedding 模型缓存（构建期下载）：混合检索的查询编码需要它
COPY --from=index /root/.cache/huggingface /opt/hf-cache

# 应用代码 + 集中配置 + 运行时数据（fixtures/nypd_real = 生产真实数据集）
COPY safepass ./safepass
COPY frontend ./frontend
COPY scripts ./scripts
COPY config ./config
COPY fixtures ./fixtures
COPY token-budget.json ./
# 索引以构建期自检通过的产物为准（覆盖仓库随带副本，消除跨环境漂移）
COPY --from=index /app/fixtures/index ./fixtures/index

# 非 root 运行；模型缓存目录属主交给运行用户
RUN useradd --system --uid 10001 --create-home safepass \
    && chown -R safepass:safepass /opt/hf-cache
USER safepass

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)" || exit 1

# 模块模式运行：cwd（/app）进 sys.path，scripts 包可解析 frontend/safepass
CMD ["python", "-m", "scripts.serve"]
