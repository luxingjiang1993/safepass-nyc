# 12 — E3 性能信封

**What to build:** 一张可复跑的表：查询 P95、紧急 P95、无 LLM 路径、有 Skill 路径、索引内存粗值。超阈测试红。数字投影到 README。

**Blocked by:** 07 — A5 画像本机可感知

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/47 （原生 blocked by #42）

- [ ] 既有性能标记可跑；阈值在配置
- [ ] 表含查询 / 紧急 / 无 LLM / 有 Skill / 内存粗值
- [ ] README 投影与测试口径同源或注明来源
- [ ] 超阈红
- [ ] `python -m pytest tests/ -q` 全绿
