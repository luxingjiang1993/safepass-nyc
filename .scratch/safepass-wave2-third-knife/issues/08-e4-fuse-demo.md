# 08 — E4 熔断演示态

**What to build:** 日预算熔断后，评级和数据还在，建议变成模板，首屏明示这次不是 AI 建议，并且不再新增模型调用。

**Blocked by:** 07 — A5 画像本机可感知

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/43 （原生 blocked by #42）

- [ ] 熔断后 suggestions_source 为模板（或等价明示），rating 仍在
- [ ] 首屏可见 degradation_notice
- [ ] 熔断后调用次数不再增加
- [ ] 紧急页不被熔断文案打乱成资料页
- [ ] `python -m pytest tests/ -q` 全绿
