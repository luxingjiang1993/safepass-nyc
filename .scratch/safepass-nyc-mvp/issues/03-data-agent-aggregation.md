# 03 — 数据 Agent 聚合

**What to build:** 对模拟 NYPD 数据集按警区聚合，产出结构化统计：12 个月 per-100k 犯罪率、样本量（真实命中记录数，动态透出、绝不硬编码）、犯罪类型 Top 5、白天/夜间案件量分布。聚合结果经接缝透出，供评级引擎、图表数据（charts 字段）与可信度档复用同一来源。

**Track:** Ralph（对应 RALPH.md T1）

**Blocked by:** 02（需要模拟数据集 fixture 才能断言逐警区数值）

**Status:** done (2026-09-04, Ralph iteration 2)

- [x] `数据Agent聚合集` 全绿：给定固定模拟数据集，逐警区断言聚合数值精确相等
- [x] sample_size 等于数据集真实命中条数（测试断言与独立计数一致，无硬编码数字）
- [x] 白天/夜间案件量分布可由时间戳字段确定性判定
- [x] sources 字段非空且含合法来源枚举（模拟数据/真实 NYPD 数据/混合）

**完成证据（iteration 2）**：`pytest tests/test_data_agent.py -q` 18 passed；`pytest tests/ -q` 49 passed（另 1 个失败 = issue 02 遗留的 BM25 pickle 协议 4/5 环境漂移，与本任务无关，见该 issue 遗留）。新增：`safepass/data_agent.py`（load_dataset 带 manifest 12 个月窗口校验，越窗记录明确失败；aggregate_precinct/aggregate_dataset 纯聚合：per-100k、sample_size、Top 5（-count,类型字典序）、昼夜由 occurred_at 确定性推导；_derive_sources 按记录来源标注透出 D8 枚举，模拟/真实并存→混合；build_charts 读集中配置 insufficient_data 档，不足档 charts=None，缺档明确失败）；`tests/test_data_agent.py`（Host 独立复算逐警区精确比对 + manifest 交叉验证；合成数据集测边界小时/Top5 并列/tiebreak、混合来源、越窗拒绝；零硬编码样本数字）。code-review 双轴审查已执行：修复 doc/代码漂移、loop 形状、12 个月窗口未强制三项；20/6 昼夜边界留代码常量（与 T0 生成脚本先例一致，RALPH grep 禁用集之外）为已记录取舍；D9 图注动态文案归契约层（issue 06）处理。遗留：同 issue 02 的 pickle 协议漂移。
