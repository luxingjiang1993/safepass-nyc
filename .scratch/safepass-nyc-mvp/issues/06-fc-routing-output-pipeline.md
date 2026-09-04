# 06 — FC 路由 + 输出控制管线

**What to build:** LLM function calling 将查询路由到声明的工具集合：`area_safety_query`、`area_comparison`、`follow_up`、`degraded_response`（路径/趋势/越界降级共用，由意图细分区分文案）、`emergency_help`（紧急兜底）。所有 LLM 结构化输出走统一输出控制管线：消费者契约 → JSON mode 生成 → 解析/修复 → Pydantic 结构 + 业务规则校验 → 有限重试（有上界）→ 明确失败。响应统一为四种契约形态（SafetyQueryResult / ComparisonResult / EmergencyResult / DegradedResult），横切字段 disclaimer/sources/sample_size 齐备，评级字段为枚举不出现自由文本。承接 03/04/05 的真实模块接入接缝，路由行为用 cassette 固定。

**Track:** Ralph（对应 RALPH.md T4；建议具体性/温暖度是 ⚠️ 主观项，只验结构，文案走标准 Implement + 人工抽查）

**Blocked by:** 03、04、05（路由目标需要真实的聚合、评级、降级模块才能端到端转绿）

**Status:** done（2026-09-04，T4；证据：`pytest tests/ -q` 124 passed 全绿，含本任务新增 27 条）

**完成证据**（对应六条勾选）：
1. 输出控制管线集：`safepass/output_pipeline.py::run_pipeline`（JSON mode → json_repair 解析/修复 → Pydantic 结构校验 → 业务校验 → 有限重试 → OutputPipelineError 明确失败）；`tests/test_output_pipeline.py` 注入损坏 JSON 两次后第三次收敛（调用恰为 3 ≤ 1+max_retries）、全损坏时调用数 == 1+max_retries（配置 `output_pipeline.max_retries=3`）、失败原因回灌下一轮
2. 契约非法被拒：rating 自由文本"相当危险"在宽松契约上被 `validate_legal_rating` 业务校验拒绝，重试耗尽后明确失败；契约层另设 `RatingEnum` Literal 双保险
3. one_liner：契约 `Field(max_length=30)` + 业务校验器双保险；接缝断言 `test_safety_result_one_liner_within_30_chars_via_seam`
4. disclaimer：四种形态（Safety/Comparison/Emergency/Degraded）均为 `Field(min_length=1)` 必填；`test_all_four_response_forms_require_non_empty_disclaimer`；装配层 `validate_non_empty_disclaimer` 再兜底
5. 建议结构：`config suggestions.safety_general` 5 条 + 空话黑名单（配置）；`make_suggestions_validator` 校验 3-5 条/非空/黑名单不单独成条；安全与降级两种形态接缝断言齐备；具体性/温暖度按任务约定转人工抽查
6. cassette：`tests/cassettes/fc_routing.json` 固定 5 条 FC 路由交互（含 capability 细分），回放底层客户端调用计数 = 0（`_FailIfCalled`），离线可重复、零真实 API；指纹与 `llm_client._fingerprint` 同源生成

**其他落地**：routing.py LLM 路径全面接入统一管线（非法路由/越权 capability 属业务校验）；ComparisonResult/EmergencyResult 定形未装配（T6/T5 归属不变，pipeline 维持显式 NotImplementedError）；perf 标记 `test_query_latency_p95_within_budget`（P95 < 6.4s 余量口径）；code-review 两轴零硬违规，已修：max_retries 改显式 `_require`（消除静默默认 0）、3-5 条边界收敛单源、one_liner 上限入契约。**遗留（判断级，未改）**：pipeline.py 两处 D12/降级 assessment 模式重复（T3 既有代码）、`degraded.build_alternative_info` 暂无调用方。

- [x] `输出控制管线集` 全绿：注入损坏 JSON → 有限重试内收敛或抛明确失败；重试次数 ≤ 配置上界
- [x] 契约非法（如 rating 自由文本）被业务校验拒绝
- [x] one_liner 存在且 ≤30 字（结构断言）
- [x] disclaimer 非空且四种响应形态都有
- [x] 建议条数 3-5 条、无空话黑名单词单独成条（结构断言；具体性与温暖度是人工项，不在本任务）
- [x] 测试路径经 cassette 固定模型行为，离线可重复、零真实 API 调用
