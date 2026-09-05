# 13 — Dockerfile + 冒烟

**What to build:** 单一 Dockerfile（多阶段：依赖 → 索引构建 → 运行时），全应用一个容器，与零服务架构故事一致；冒烟脚本（容器起得来、首页 200）；部署产物静态校验进 pytest。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M4 部署（spec v2）

- [ ] `docker build` 成功，单容器跑起应用 —— 交付：多阶段 Dockerfile（deps → index → runtime）+ 入口 `scripts/serve.py`；本机 Docker 守护进程未运行，真机构建属人工出口（spec Testing Decisions）
- [ ] 冒烟脚本通过（首页 200、查询页可达）—— 交付：`scripts/docker_smoke.sh`；容器内实跑属人工出口。入口已在本机以生产数据集实跑验证（首页/覆盖区查询/越界降级三路由均 200）
- [x] Dockerfile 关键指令静态校验进 pytest —— `tests/test_dockerfile.py` 17 项（多阶段结构、基镜像钉版、索引构建自检、离线运行、非 root、端口一致性、COPY 资产存在性、dockerignore、冒烟脚本结构）
