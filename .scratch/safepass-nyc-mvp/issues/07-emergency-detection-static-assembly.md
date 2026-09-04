# 07 — 紧急检测两层 + 静态紧急组装

**What to build:** 紧急检测第一层：关键词静态表命中即进无 LLM 静态分支，优先于一切 LLM 调用；第二层：FC 路由中的 `emergency_help` 工具兜底（用户用不含关键词的表述描述紧急情况时由路由层接住，路由判定后同样不再生成自由文本）。EmergencyResult 由静态模板 + 警区静态表直接组装：911 中文引导（"I need help. Can I have a Chinese interpreter?"）、报警信息准备清单（位置/发生了什么/是否需要救护车/嫌疑人特征）、安抚话术、按警区安全场所清单（便利店/医院/警局）或通用清单（911/311 + 五警局地址电话）、311 与社区协助电话。无区域查询历史时不出现"最近""离你最近"等暗示定位的词。静态分支全程 <2s。

**Track:** Ralph（对应 RALPH.md T5；改写句层用 cassette 回放，LLM 真实兜底召回率转人工验收清单在线验证）

**Blocked by:** 02（需要警区安全场所静态表 fixture）

**Status:** done（2026-09-04，T5；证据：`pytest tests/ -q` 153 passed 全绿（唯一失败为 T0 遗留的 BM25 pickle 协议漂移，见 issue 02，与本任务无关），含本任务新增 30 条；`-m perf` 2 passed）

**完成证据**（对应五条勾选）：
1. 紧急触发集：`tests/test_emergency.py`——12 条关键词直录 + 6 条改写句经唯一接缝 `execute_query` 全部产出 EmergencyResult（合计触发率 100% > 95%）；改写句层用 `tests/cassettes/emergency_fc.json`（6 条交互，指纹与 `llm_client._fingerprint` 同源生成）回放验证，回放底层调用计数 = 0；接缝注意：cassette 游标按文件全局顺序消费，多交互回放须在单条用例内顺序消费（同 fc_routing.json 先例）
2. 静态分支 0 次 LLM 调用：第一层 `emergency.is_emergency`（config `emergency.keywords` 24 词）在 `pipeline.execute_query` 中位于路由之前（优先于一切 LLM 调用）；注入计数 fake 断言 `fake.calls == 0`；第二层路由 `emergency_help` 判定后全管线仅 1 次 LLM 调用（路由本身），静态组装不再生成自由文本
3. < 2s：`test_emergency_assembly_latency_p95_within_budget`（perf 标记，20 次取样 P95 < 2s × 0.8 = 1.6s 余量口径，实际毫秒级）
4. 清单逐字段一致：按警区查询（"我在法拉盛被跟踪了"）→ `venues` 与 `fixtures/safe_places/precinct_safe_places.json` 的 `precincts["109"].venues` 逐字段相等；无区域/越界（"哥大附近"→26 静态表无条目）→ 通用清单（911/311 + 五警局）逐字段相等；无定位词：`emergency.proximity_blacklist`（配置）双层断言（装配层守卫 `make_proximity_guard` + 测试集文本扫描），覆盖 "最近"/"离你最近"
5. 字段断言（AC-014）：`call_911_prompt`（含 911 引导）、`chinese_interpreter_phrase`（PRD 原文 "I need help. Can I have a Chinese interpreter?"）、`info_checklist`（恰好 4 条：位置/发生了什么/是否需要救护车/嫌疑人特征）、`comfort_message`、`non_emergency_contacts`（含 311 电话）均非空；配置缺 `emergency` 段 → ConfigError 显式失败

**其他落地**：`safepass/emergency.py` 两层检测 + 静态组装 + 装配自检（AC-014 字段校验器 + 无定位词守卫 + disclaimer）；`config_loader.EmergencyConfig`（keywords/模板/proximity_blacklist 全部 `_require` 显式读取，无静默默认）；`pipeline.py` emergency/follow_up 未落地分支拆分（follow_up 仍显式 NotImplementedError 归 T6）；test_degraded.py 的 T5 占位测试改为"第二层仅一次 LLM 调用 → 静态 EmergencyResult"断言。**code-review 两轴零硬违规，已修**：①第二层 emergency_help 排序提到 D12 之前（两轴共指：紧急响应时间敏感且不消费数据集，越界区域的紧急改写句不再被降级吞掉；回归测试 `test_layer2_emergency_precedes_d12_for_out_of_coverage_area` 锁定）；②emergency.py 静态表 JSON 单次解析 + 删除废弃的警区号返回值 + `NON_EMERGENCY_VENUE_TYPE` 具名常量；③EmergencyResult 核心话术字段结构层 `Field(min_length=1)`（对齐 disclaimer 模式，T4 两个直接构造契约的测试同步补最小合法字段）。**遗留（判断级，未改）**：①社区协助电话——静态表护栏禁止录入无官方来源号码，non_emergency_contacts 诚实只含 311（静态表补录后过滤自然生效）；②"查询过的区域"依赖 session_state 消费，按任务划分归 T6；③关键词纯子串匹配的误报率（如"报警电话是多少"）不在本任务判定范围，F5-1 关键词库扩充在人工验收清单；④LLM 真实兜底召回率按 RALPH 约定转人工验收清单在线验证（cassette 层只证机制不证真实准确率）。

- [x] `紧急触发集` 全绿：关键词直录 + 改写句合计触发率 > 95%（改写句层用 cassette 回放验证）
- [x] 静态分支 LLM 调用计数 = 0
- [x] EmergencyResult 组装 < 2s（perf 标记，P95 计时留 20% 余量）
- [x] 清单字段与警区静态表逐字段一致；无历史查询时出通用清单且无定位词
- [x] 字段断言：911 按钮文案、中文报警用语、信息准备清单、安抚话术、311/社区电话均非空
