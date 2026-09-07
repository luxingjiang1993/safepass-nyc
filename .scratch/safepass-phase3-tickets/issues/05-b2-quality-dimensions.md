# 05 — B2 质量维度：actionability + specificity + 矛盾检测

## 执行方式 / 并行组
- **方式：/implement**（新 judge 维度设计，探索性）
- **依赖**：B1（#19）合并
- **并行组**：槽 4，与 E1（#23）同槽但串行——本票先落 README 指标行，E1 后收口叙事
- **文件冲突警示**：evaluators.py / config eval 节 / README 指标表
- **阻塞**：E1（#23）

## 来源
docs/portfolio-100-execution-plan.md §2 B2 + 文首补丁 P6

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：除 groundedness/幻觉外，能量化「能照做」「提到本区数据」「不与 charts 矛盾」。
- **做法**：规则特征（含数字/时间/offense 名）+ LLM-judge 维度；矛盾用确定性核对（提及「夜间更安全」但 night>>day → fail）。
- **DoD**：三类指标进 README 或 eval 工件；有回归门。
- **加分**：从 1 个虚荣指标 → 质量仪表盘。

## Phase 3 开赛定案（P6，效力优先）

1. 依赖 B1 的两路径 runner 与重录好的 cassette；本票只扩维度，不再单独重录（如必须改 judge 提示词才重录，遵守棘轮）。
2. 矛盾检测是确定性核对（数据事实 vs 建议文本），不许 LLM 判定。
3. 指标口径进 README 质量基线表（与 B1 的两路径对照表同页）。

## 允许改动
- `tests/eval/`（新维度 judge + 确定性矛盾核对）
- `safepass/evaluators.py`（维度实现，标注 provenance）
- `config/app.yaml`（eval 节：新维度开关/阈值）
- README（指标表）

## 禁止
- 矛盾检测用 LLM 判定
- 引入 deepeval/ragas 运行时（只借维度灵感，改写进本仓）

## 验证
- `python -m pytest tests/ -q`
- `python -m pytest tests/eval -q`

## 完成承诺
- actionability/specificity/矛盾三类指标进 README 或 eval 工件，有回归门；矛盾核对确定性实现；两套件全绿。
