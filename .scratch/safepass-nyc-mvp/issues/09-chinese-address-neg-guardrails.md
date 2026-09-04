# 09 — 中文地址识别 + NEG 负例防线

**What to build:** 在 05 的最小地址解析上扩展中文地址识别与别名映射：覆盖 10 个常见中文地址（含"上东区""法拉盛""哥大附近"→26 警区、"布鲁克林 Heights"等映射别名），识别区域/人群/时间三维提取。同时落地 NEG-001~009 负例行为防线：种族偏见诱导问题拒绝并转向结构性解释、武器防身建议拒绝并引导合法途径、结果不暴露个体受害者信息、无恐慌性夸大、免责声明每处存在、同一区域在有/无画像与不同问法下评级字段完全一致（画像不变性，ADR-0002）。

**Track:** Ralph（对应 RALPH.md T7；画像措辞易懂是 ⚠️ 主观项转人工抽验）

**Blocked by:** 05（地址解析最小版与越界判定）、06（三维提取经 LLM 层，需管线与 cassette 基建）

**Status:** done（2026-09-04，证据见下）

- [x] `中文地址识别集` 全绿：10 个常见中文地址 10/10（对齐 PRD UX-002）；扩展标注集 > 90%
- [x] 契约中断言提取的三维字段（区域/人群/时间）
- [x] `画像不变性集` 全绿：同一区域 × 有/无画像 × 不同问法，评级字段完全一致且与阈值规则复算一致
- [x] `负例集` 全绿：NEG-001~009 全部通过（种族偏见转向、武器拒绝、无个体隐私、无恐慌夸大、免责声明存在）
- [x] 画像声明字段存在（"会话级、关闭即删除"；措辞易懂是人工项，不在本任务）

**完成证据**：`pytest tests/ -q` 221 passed 全绿（含 perf）。新增测试集：
`tests/test_chinese_address.py`（中文地址识别集，40 用例含 AC-002）、
`tests/test_profile_invariance.py`（画像不变性集）、`tests/test_guardrails.py`（负例集）。
实现：contracts 增 `ExtractedDimensions` + `GuardrailResult`（判别联合第 5 形态，spec D3
原文仅四种，系本 issue 负例防线的实现侧扩展，已在 contracts.py 与 test_guardrails.py
头部注释声明）；新 `safepass/extraction.py`（三维提取：注入客户端走输出控制管线
[cassette 固定]，追问轮与离线走确定性 fallback）；新 `safepass/guardrails.py`
（bias/weapon 静态守卫零 LLM，panic 黑名单为装配自检）；pipeline 接入画像消费
（人群建议排序前置 + 晚归时间提示前置，评级零接触）。新增 cassette：
`extraction_ac002.json`（2 交互：路由+提取）、`fc_routing_seam.json`（接缝路由用例
T7 起消费 2 次 LLM 调用，从共享 fc_routing.json 拆出）。配置新增 `guardrails:` 与
`profile:` 段（config_loader 显式校验）。T6 遗留 F3-2 女性安全维度留位未动（对比
维度表扩充非本 issue 勾选项）。画像措辞易懂、LLM 提取真实准确率 = 人工/在线验收项。
