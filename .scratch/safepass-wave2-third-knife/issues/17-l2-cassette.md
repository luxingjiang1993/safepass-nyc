# 17 — L2 重录 cassette

**What to build:** C2 / C3 / A5 改变生成物或契约序列化后，重录 L2 cassette 与评测工件。回放全绿。不改 judge 提示词。不动 N2 三列 cassette。

**Blocked by:** 01 — C2 四时段桶（灯不变）；05 — C3 罪名中文映射；07 — A5 画像本机可感知

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/52 （原生 blocked by #36、#40、#42）

- [ ] 前置三票已合并且默认基线绿之后才录
- [ ] `python -m pytest tests/eval -q` 回放全绿
- [ ] 默认 `python -m pytest tests/ -q` 仍不收集评测目录
- [ ] 未改 N2 cassette；未改 judge 提示词
- [ ] 需开发模型密钥与日预算；无 key 本票不能收口
