# 05 — 降级分支 + D12 确定性后置

**What to build:** 路径查询、趋势查询、越界查询（含"哥大附近"→26 警区）、中城查询（跨 14/18 警区，明确不在覆盖清单）→ DegradedResult：开发中/无数据说明 + 替代信息（所在区域评级/时间模式，若在覆盖内）+ 重新选择邀请 + 通用建议与紧急资源；零路径级/趋势级结论、零编造。地址解析的**最小版**在本任务引入（警区映射 + 覆盖清单判定）；D12 越界判定确定性后置：解析出警区 ∉ 覆盖清单 → 无条件产出 DegradedResult，该校验发生在 FC 路由之后、数据查询之前，即使 LLM 误路由到 `area_safety_query` 也会被强制改写。

**Track:** Ralph（对应 RALPH.md T3；诚实原则基石，Ralph 优先）

**Blocked by:** 02（需要 fixture 中"哥大附近"等映射别名与越界案例）

**Status:** done (2026-09-04, 标准 Implement；先红后绿)

- [x] `降级行为集` 全绿：路径/趋势/越界/中城/单边越界对比每类输入断言 type=degraded、degraded_capability 正确、覆盖内时替代信息含真实评级
- [x] 响应文本不含路径级词汇黑名单（如"路线风险""照明""替代路线"），零编造
- [x] D12 后置校验用例通过：LLM 误路由越界查询被强制改写为 DegradedResult
- [x] 数据不足输入（样本量 <10）→ unknowns 非空、charts 为 null（契约中隐藏图表模块）

**完成证据**：`pytest tests/ -q` 92 passed（新增 18 条降级行为集）。新增/改写：
- `config/app.yaml`：`addressing.aliases`（上东区→19…哥大附近→26、中城→[14,18]，警区号唯一居所）、`degraded`（path/trend 静态标记 + 四级说明模板 + 重新选择邀请 + 通用建议）、顶层 `disclaimer`；
- `safepass/contracts.py`：Pydantic 判别联合（DegradedResult / SafetyQueryResult 最小版 / ComparisonResult 最小版；EmergencyResult 留 T5）；
- `safepass/addressing.py`：地址解析最小版（长别名优先 + 重叠去重 + 覆盖判定，零 LLM、零警区号字面量）；
- `safepass/routing.py`：FC 路由最小版（静态意图标记优先，注入 llm_client 时单轮 JSON 询问；有限重试/修复属 T4）；
- `safepass/degraded.py`：降级装配（替代信息 = 数据 Agent 聚合 + 评级引擎真实输出；紧急资源逐字段来自 safe_places 通用清单）；
- `safepass/pipeline.py`：execute_query 填入最小实现，执行序 = 地址解析 → FC 路由 → **D12 后置校验（路由后、数据查询前，无条件强制改写）** → 降级/安全/对比分支；
- `safepass/data_agent.py`：新增 `load_time_range()`（契约 time_range）。
- 测试维护：`tests/test_degraded.py`（18 条，含黑名单扫描、D12 三个强制改写用例、⚪ unknowns/charts、紧急资源逐字段比对）；`tests/test_skeleton.py` 两条 issue-01 空壳断言更新为"接缝已填入最小实现"（空壳约定被 T3 取代）；`tests/test_data_agent.py` AppConfig 构造改 dataclasses.replace（配置 schema 扩展）。
- 遗留：画像/会话状态在管线签名冻结但未消费（T4/T6）；建议生成、社区信息、紧急模式、追问按 RALPH.md 后续切片；完整中文地址识别（10/10 地址集）属 T7。无 git 仓库（文件连接器即 tracker），未提交。
- 审查修复（/code-review 双轴，2026-09-04）：① 降级响应 sources 改原样透出数据 Agent 来源标注（spec D8，废弃硬编码"模拟数据"字面量）；② 未识别区域的 path/trend/普通查询不再抛 ValueError，统一进 DegradedResult 契约（新增 path_generic/trend_generic/unrecognized 配置模板）；③ emergency_help/follow_up 路由与双覆盖区对比在 T5/T6 落地前显式 NotImplementedError，不静默吞掉；④ 移除越界的 ComparisonResult 最小实现（死条件一并清除）；⑤ 「从…到…」成对标记下沉 config `path_pair_markers`；⑥ 聚合+评级收敛为 `degraded.assess_area` 单点。修复后 `pytest tests/ -q` 97 passed（降级行为集 23 条）。
