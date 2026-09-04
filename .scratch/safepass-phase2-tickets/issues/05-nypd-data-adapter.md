# 05 — 真实数据 adapter（Socrata 单向管道）

**What to build:** 从 NYC Open Data（Socrata API）拉取真实 NYPD 犯罪数据的离线脚本：单向管道，手动/月更运行，运行时（产品代码）永不直连外部 API。HTTP 层可注入；入库前校验（缺字段/时间越界/警区不在清单）不合格即拒收并报告；来源标注落盘（resource-manifest 诚实护栏）。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M2 数据 + 成本（spec v2）

- [ ] adapter 脚本可运行，产出落 `fixtures/nypd_real/`，来源标注齐
- [ ] 三类校验拒收路径有测试（缺字段/时间越界/警区不在清单）
- [ ] Socrata 响应走录制 fixture，测试离线可跑（Socrata 匿名可调，无需 key；录制需网络）
- [ ] 老测试不破
