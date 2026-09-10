# 04 — E2 契约版本说明

**What to build:** 安全查询结果等契约在本阶段增字段或稳定字段时，仓库里有一段短版本说明和前端兼容策略，避免「多了一个字段没人知道」。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/39

- [ ] 短 changelog 或 ADR 一节列出本刀相关字段（含已有评级依据、本刀时段桶 / 中文罪名展示）
- [ ] 写清未知新字段时前端不得崩、不得假装有依据
- [ ] 不引入服务型 API 版本号体系
- [ ] `python -m pytest tests/ -q` 全绿
