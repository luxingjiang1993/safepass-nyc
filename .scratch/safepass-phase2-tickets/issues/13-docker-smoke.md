# 13 — Dockerfile + 冒烟

**What to build:** 单一 Dockerfile（多阶段：依赖 → 索引构建 → 运行时），全应用一个容器，与零服务架构故事一致；冒烟脚本（容器起得来、首页 200）；部署产物静态校验进 pytest。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M4 部署（spec v2）

- [ ] `docker build` 成功，单容器跑起应用
- [ ] 冒烟脚本通过（首页 200、查询页可达）
- [ ] Dockerfile 关键指令静态校验进 pytest
