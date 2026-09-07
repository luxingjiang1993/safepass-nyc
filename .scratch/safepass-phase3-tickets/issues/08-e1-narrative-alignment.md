# 08 — E1 叙事与代码对齐

## 来源
docs/portfolio-100-execution-plan.md §2 E1 + 文首补丁 P6 + docs/adr/0003-suggestion-generation-architecture.md

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：消灭「文档承诺 > 代码」的面试地雷。
- **DoD**：`skills/`、CONTEXT、README 三处一致。
- **加分**：诚信；避过「课程作业感」。
- **硬规则**：A1 未合并前，禁止 Hero/README 写「AI 建议」；只能写数据评级 + 即将/已用模板建议。

## Phase 3 开赛定案（P6，效力优先）

1. 本票依赖 A1 合并后执行（A1 未合并前 Hero/README 禁止「AI 建议」）。
2. README 主路径描述 = LLM 建议正文（带依据/数据钩子）+ 确定性 one_liner；不得写「画像个性化建议」暗示画像送 LLM。
3. 隐私页「零上传」口径在 A1 落地后保持不变——三处（skills/README、CONTEXT.md、隐私页）交叉核对。

## 允许改动
- `README.md`（主路径叙事）
- `CONTEXT.md`（与代码对齐的措辞）
- `docs/`（仅叙事一致性，禁止借机改产品范围）

## 禁止
- 借机改产品范围/评级口径
- 在隐私页写与 ADR-0003 冲突的表述

## 验证
- `python -m pytest tests/ -q`
- 三处关键词 grep 交叉核对（README 承诺 ↔ 代码实现）

## 完成承诺
- skills/、CONTEXT.md、README 三处对建议主路径的描述一致；隐私页口径与 ADR-0003 一致；基线全绿。
