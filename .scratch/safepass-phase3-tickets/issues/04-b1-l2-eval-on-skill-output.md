# 04 — B1 L2 咬合生成建议（两路径对照，禁止测模板自嗨）

## 来源
docs/portfolio-100-execution-plan.md §2 B1 + 文首补丁 P6 + docs/adr/0003-suggestion-generation-architecture.md

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：groundedness / 幻觉率反映 Skill 输出，不是 `safety_general`。
- **做法**：金标带 `must_mention` / `must_not_claim` 对准建议与 one_liner；模板降级路径单独 marker，不计入主 groundedness。
- **DoD**：关掉 Skill 改回纯模板时，主指标应明显变差或套件失败；README 口径写清。
- **加分**：Hamel 标准下的真 eval。
- **Craft**：S1。

## Phase 3 开赛定案（P6，效力优先）

1. **DoD 改为两路径同台对照**（原 DoD 循环论证已废弃）：同一金标分别跑 Skill 路径与确定性模板路径，**Skill 主指标 ≥ 模板才收口**，对照数字进 README；打不过就迭代到打得过再收。
2. one_liner 走确定性（A3），one_liner 断言不进 LLM judge，只进 L1 金标。
3. 改提示词/口径 → 必须重录 L2 cassette 并跑 `python -m pytest tests/eval -q`（CLAUDE.md 棘轮流程）。
4. 模板降级路径单独 marker，不计入主 groundedness（计划原文保留）。

## Craft
- Craft IDs: S1
- **必须打开（产品 URL）**：https://www.perplexity.ai/ （看「可核对断言 + 来源」形态）
- **观察清单**：无来源时不装成有来源；追问改答案焦点
- **借鉴什么 / 别抄什么**：借 grounds 可核对性进 judge 判定；禁止实时搜索

## 允许改动
- `tests/eval/`（l2_runner 咬合 Skill 输出 + 两路径对照 runner）
- `tests/cassettes/`（重录）
- `fixtures/eval/golden_set_v1.json`（must_mention/must_not_claim 对准建议与 one_liner 修订）
- `scripts/record_l2_cassette.py`（如口径变化需适配）
- README（质量基线表口径：主指标 = Skill 路径；附两路径对照表）

## 禁止
- 用「看起来更好」的散文代替数字
- 保留「关掉 Skill 必须变差」的预设断言
- 重录 cassette 时混用模型（dev = DashScope Qwen 为准）

## 验证
- `python -m pytest tests/ -q`
- `python -m pytest tests/eval -q`
- 两路径对照数字落 README 或 eval 工件

## 完成承诺
- 主 L2 指标反映 Skill 输出；两路径对照数字在 README/工件可查且 Skill ≥ 模板；cassette 重录后 eval 套件全绿；基线全绿。
