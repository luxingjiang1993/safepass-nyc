# 08 — 追问上下文承接

**What to build:** 会话状态只持有上轮查询的结构化结果（地点、评级、数据摘要），不存完整对话历史。两种合法追问承接：对比追问（"那和布鲁克林 Heights 比呢？"→ 走对比流程）与细节追问（"女生晚上呢？"→ 承接上轮地点叠加人群/时间维度）。换地点或换话题即视为新查询：`follow_up` 路由失效、会话状态重置、走新查询流程。对比追问越界时按单边越界规则：覆盖区出分析，越界侧只有 out_of_coverage 说明、无对比结论。

**Track:** Ralph（对应 RALPH.md T6）

**Blocked by:** 05（单边越界与降级规则）、06（follow_up 路由与会话状态载体的接缝接入）

**Status:** done（2026-09-04，T6；先红后绿；证据：`pytest tests/ -q` 178 passed 全绿，含本任务新增 24 条追问集；`-m perf` 2 passed）

**完成证据**（对应四条勾选）：
1. 承接正确：`tests/test_followup.py` 24 条——对比追问承接（ComparisonResult 两侧地点/评级/样本量与 Host 复算一致，84 警区 n=6 ⚪ 分支断言 decision_aid=None 的诚实口径）、细节追问叠加（dimensions={人群：女生， 时间：晚上}，评级与直查不变）、AC-021 四段叙事全链路（查询→对比追问→细节追问→换地点）、AC-016 直问对比（area_comparison 路由 + 会话状态承接）与双覆盖区直查对比（零 LLM 确定性出对比）。
2. 重置明确：换地点（"那法拉盛呢？"→ 仅分析新地点，叙事字段无上轮区域残留）/换话题（"纽约哪里租房便宜呢？"→ unrecognized 降级，message 与模板逐字相等）/无会话状态/多区域追问/有对比标记无可比目标 → `followup.classify` 一律 KIND_TOPIC_SHIFT，管线置空 session_state 走新查询统一流程。
3. 追问越界 F3-5："那和哥大附近比呢？"→ DegradedResult(out_of_coverage)，替代信息=上轮覆盖侧（19）真实评级，契约 dump 无 areas/winner/decision_aid/verdict 任何对比结论字段。
4. 零持久化：`test_session_state_zero_persistence_via_seam` 多轮追问全程后对 config/fixtures/cassettes 三目录做 (mtime_ns, size) 快照比对，零变化；`session_state.py` 为纯数据定义（SessionState/AreaSnapshot，字段集即"不存对话历史"的结构防线），降级/紧急响应对 from_result 抛 TypeError 不产出伪承接。

**其他落地**：`config/app.yaml` 新增 `followup`（对比/时间/人群标记，确定性细分用）与 `comparison`（决策辅助模板）节；`config_loader.py` 新增 FollowUpConfig/ComparisonConfig（非空校验，无静默默认）；`safepass/session_state.py`（上轮结构化结果载体，from_result 规则：Safety→单快照 / Comparison→last=末位区域 / Degraded·Emergency→TypeError）；`safepass/followup.py`（确定性细分，零 LLM，D12 同款后置思路）；`safepass/comparison.py`（对比装配：AreaSummary 逐字段来自本次聚合，维度表 available/in_development，决策辅助按真实评级+夜间占比交叉相乘比较填充，任一侧 ⚪ → None）；`pipeline.py`（follow_up 承接 + area_comparison 单区域承接 + 双覆盖区直查对比 + `_single_side_ooc_degraded` 统一 F3-5/D12 单边越界装配）；`contracts.py`（AreaSummary 扩展 day_night/top5_types，ComparisonResult.dimensions）。cassettes：`tests/cassettes/followup_*.json` 6 个单交互录制（回放底层调用计数=0，离线可重复）。`tests/test_degraded.py` 两条 T6 占位测试改写为新行为断言。
**审查**（/code-review 双轴；子代理因配额失败，转内联执行）：Standards——词汇零违规（grep 置信度/多轮对话等避免词）、无散落阈值/警区字面量、显式失败约定（assert 改 ValueError）；修复：F3-5 装配形状重复收敛为 `_single_side_ooc_degraded` 单点。Spec——issue 四条勾选全覆盖；**遗留（判断级）**：F3-2 女性安全对比维度随 T7 三维提取落地后扩充（comparison.py `_DIMENSION_STATUSES` 已留扩展位，人群维度标记表已在 config.followup.crowd_markers）；决策辅助为数据驱动（两侧均评级即存在），"有画像时存在"的结构断言由其实质覆盖。无 git 仓库（文件连接器即 tracker），未提交。

- [x] `追问集` 全绿：对比追问/细节追问承接正确（地点、评级、维度叠加均断言）
- [x] 换地点/换话题不复用上轮结构化结果，重置明确
- [x] 追问越界走单边越界规则：越界侧无对比结论字段
- [x] 会话状态零持久化：仅存在于当前会话，接缝级断言不含任何落盘行为
