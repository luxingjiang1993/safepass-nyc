# 04 — 评级引擎 + 可信度映射（纯函数）

**What to build:** 纯函数评级引擎：输入数据 Agent 的统计 + 全市均值 → 输出安全评级枚举（🟢🟡🔴⚪）与可信度档（HIGH/MODERATE/LOW）。阈值系数（0.7×/1.3×）与样本量四档全部读集中配置；样本量 <10 时强制 ⚪ 数据不足，不给出评级、不给可信度；可信度与评级同源（同一 sample_size 输入），每档附固定自然语言解释（如"基于本次查询命中的 N 条记录，数据量适中"）。零 LLM 参与、零画像参与（ADR-0001/0002）。

**Track:** Ralph（对应 RALPH.md T2；纯函数零 LLM，Ralph 最优先的信任基石之一）

**Blocked by:** 02（需要覆盖四档与边界案例的 fixture 才能复算）

**Status:** done (2026-09-04, Ralph iteration 3)

- [x] `评级可复算集` 全绿：对覆盖区逐警区用阈值规则独立复算期望评级，与引擎输出 100% 一致（含 ⚪ 分支）
- [x] 边界值用例通过：恰 0.7×、恰 1.3×、恰 10 条、恰 30 条、恰 100 条
- [x] 函数签名与实现中无 LLM 客户端、无画像参数
- [x] 可信度档随评级同源输出，<10 时评级与可信度均为空/⚪

**完成证据（iteration 3）**：`pytest tests/test_rating_engine.py -q` 24 passed；`pytest tests/ -q` 73 passed（另 1 个失败 = issue 02 遗留 BM25 pickle 协议漂移，非本任务引入）。新增：`safepass/rating_engine.py`（`rate_precinct(stats, cfg)` 纯函数：ratio=per-100k/全市均值，`<green_max`→🟢、`≤red_min`→🟡（含两端）、`>red_min`→🔴，全部读配置；样本量强制档⚪不给评级/可信度/解释；可信度解释=配置模板 `.format(n=真实命中数)`；全市均值缺失/解释模板缺失/档位无匹配均明确失败 ConfigError）；`tests/test_rating_engine.py`（Host 独立复算逐警区 100% 比对含⚪；边界用例经 `math.nextafter` 在配置阈值两侧浮点精确取值 + 样本档边界从配置推导恰每档首数/前一数；签名检查无 profile/llm_client；`test_config_values_match_spec_d4` 把 spec D4 数字钉死为配置↔spec 唯一机器锚点——review 发现的"推导式边界测试配置漂移仍会绿"缺口）。code-review 双轴审查：零违规、零错误实现（手工抽验 P19/P109/P5/P90/P84 与 manifest 一致）；修复测试内 AppConfig 逐字段重建重复（改 `dataclasses.replace`）与双重调用小低效；⚪ 分支仍带 ratio 基准字段（spec 未禁止，D3 无条件列出）记为已知取舍。遗留：同 issue 02 pickle 漂移；AC-009 计数半由 T1 聚合集闭环（本集只验同源透传，符合 AC→Sensor 表归属）。
