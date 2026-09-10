# 10 — D3 空态 / 加载 / 部分失败

**What to build:** 无结果、加载中、提取失败、索引缺失、熔断降级各有明确页面态。降级说明在覆盖内首屏可见。

**Blocked by:** 09 — D4 视觉网格、浅深主题与十槽插画

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/45 （原生 blocked by #44）

- [ ] 上述各态有可测 HTML 或接缝形态
- [ ] 覆盖内熔断 / 模板降级：degradation_notice 首屏可见
- [ ] 加载态不引入前端框架
- [ ] 紧急页不套用资料页空态
- [ ] `python -m pytest tests/ -q` 全绿
