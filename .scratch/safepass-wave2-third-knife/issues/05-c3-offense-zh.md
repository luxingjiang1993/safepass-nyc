# 05 — C3 罪名中文映射

**What to build:** Top5 图表与建议正文使用同一套中文罪名。配置里没有的类型外显「其他」，计数不丢。

**Blocked by:** 01 — C2 四时段桶（灯不变）

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/40 （原生 blocked by #36）

- [ ] 映射只在配置；图表与建议共用
- [ ] fixture 已出现的类型有中文名
- [ ] 未知类型 →「其他」，计数保留、不静默吞掉
- [ ] 无运行时翻译 API
- [ ] `python -m pytest tests/ -q` 全绿（本票不跑、不等 L2 重录）
