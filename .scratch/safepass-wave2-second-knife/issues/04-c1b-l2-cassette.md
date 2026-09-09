# 04 — C1b 重录 L2 cassette

**What to build:** C1a 把评级依据写进完整安全查询结果后，L2 judge 请求指纹会变。重录 L2 cassette 与评测工件，评测套件离线回放全绿。不把 L2 拉进默认行为基线；不动 N2 三列 cassette。

**Blocked by:** 01 — C1a 评级依据人话（契约 + 首屏替换）

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/29

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/33 （原生 blocked by #30）

- [ ] C1a 已合并且默认基线绿之后才录制
- [ ] L2 回放 `python -m pytest tests/eval -q` 全绿
- [ ] 默认 `python -m pytest tests/ -q` 仍不收集评测目录
- [ ] 未改 N2 对照 cassette；默认不改 judge 口径（除非指纹证明必须改，须在本票说明）
- [ ] 需开发模型密钥与日预算；无 key 本票不能收口
