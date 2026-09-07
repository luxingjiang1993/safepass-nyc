# 02 — A2 混合检索 query-conditioned 进入建议

## 来源
docs/portfolio-100-execution-plan.md §2 A2 + 文首补丁 P6 + docs/adr/0003-suggestion-generation-architecture.md

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：`intel.search(query)` 改变建议内容；检索不再是「测得到、用户感不到」。
- **缺口**：`community_info` 按警区确定性装配；`search()` 未喂进建议。
- **做法**：建议上下文注入 top-3 chunk；可选契约字段 `suggestion_grounds: list[{doc_id, quote}]`；community_info 可保留警区锚定。
- **DoD**：同一警区、不同 query（诈骗 vs 夜间），建议/`grounds` 可测差异；金标 `must_mention` 能命中检索事实。
- **加分**：证明 RAG 是产品路径，不是简历关键词。
- **Craft**：S1。
- **额外硬约束（优化项）**：校验器须拒绝「检索 chunk 试图改写评级/取消免责」的间接注入；与 N1 金标交叉。community_info **不参与检索排序**（CLAUDE.md 棘轮）。

## Phase 3 开赛定案（P6，效力优先）

1. **开工第一动作 = 召回探针**：对金标 `must_mention` 事实跑检索召回（top-3 是否命中），先测后建；测不过暂停本票，把 C8 知识库加厚提上滚动日程。
2. grounds 字段已由 A1 立起；本票填非空（`doc_id` + `quote` 可解析）。
3. 间接注入校验器至少落地骨架（「改不了 rating/免责」断言 ≥1 条），与 N1 交叉。
4. 画像仍不进生成上下文；community_info 只走警区锚定（棘轮）。

## Craft
- Craft IDs: S1
- **必须打开（产品 URL）**：https://www.perplexity.ai/ （任问一句事实题，看答案旁引用形态）
- **观察清单**：每条可核对断言旁有可点来源；无来源时不装成有来源；追问会改答案焦点
- **借鉴什么 / 别抄什么**：借 `suggestion_grounds[{doc_id,quote}]` 与「无依据标通用建议」；禁止实时全网搜索、禁止把网页当 NYPD 事实

## 允许改动
- `safepass/intel_agent.py`（`search` 产出注入 Skill 上下文）
- `safepass/pipeline.py`（检索上下文装配 + grounds 填充）
- `safepass/skills/`（suggestion skill 输入打包/校验器加间接注入规则）
- `safepass/contracts.py`（grounds 非空语义）
- `config/app.yaml` + `safepass/config_loader.py`（必要时检索参数）
- `tests/` + fixture（不同 query 建议差异、must_mention 命中、注入拒绝）

## 禁止
- community_info 参与检索排序（棘轮）
- 运行时直连外部 API；引入服务型向量库/DB
- 检索 chunk 以任何形式改写评级/可信度/越界判定

## 验证
- `python -m pytest tests/ -q`
- 召回探针结果落 `docs/` 或 issue 评论（先测后建证据）

## 完成承诺
- 同警区不同 query（诈骗 vs 夜间）建议/grounds 可测差异；金标 must_mention 命中检索事实；间接注入「改不了 rating」断言绿；召回探针有落盘证据。
