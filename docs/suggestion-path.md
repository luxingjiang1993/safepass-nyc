# G2 建议路径对照说明

审阅者用这一页核对成长路径：**曾经**建议正文来自配置模板；**现在**主路径是 Suggestion Skill + 混合检索定调。灯（安全评级）与可信度、越界判定从未交给 LLM。

- 票：GitHub `#50` / 第三刀 G2
- 架构决议：[`docs/adr/0003-suggestion-generation-architecture.md`](adr/0003-suggestion-generation-architecture.md)
- 产品接缝：`execute_query`（`safepass/pipeline.py`）
- 画像本机可感知（A5）：`tests/test_a5_profile_local.py`

## 前后对照

| 维度 | 曾经（配置模板建议） | 现在（Skill + 检索） |
|------|----------------------|----------------------|
| 建议正文 3–5 条 | 按评级/场景从配置拼确定性模板文案 | Suggestion Skill（LLM 措辞）生成；须过输出管线校验 |
| 事实定调 | 仅数据钩子填空（无检索引文） | 混合检索 top-3 摘要进 Skill；`suggestion_grounds` 要求 quote 逐字命中原文、doc_id 闭合 |
| 来源明示 | `suggestions_source=template` | 主路径 `skill`；校验耗尽 / 熔断 / 无 key → 仍降级为 `template`，且不静默 |
| 首屏核心结论行 | 确定性 `one_liner`（数据钩子） | **不变**：仍是确定性模板，LLM 不写 |

「曾经」指 Phase 2 / 波 1 前主路径：建议层不接生成式模型，正文全部来自配置模板。波 1 A1 起主路径改为 Skill；模板路径保留为降级与两路径对照（B1），不是第二套产品。

## 安全评级不变式（零 LLM）

下列判定**始终**是纯函数 / 确定性后置，LLM 零参与（宪法红线 2、ADR-0001/0002）：

| 不变式 | 谁写 | 说明 |
|--------|------|------|
| 安全评级（灯） | `rating_engine` | 同输入同输出；不读画像、不读 Skill 产出 |
| 可信度档 | 样本量规则（配置档位） | 与评级一并确定性写出 |
| 越界判定 | D12 后置 | 警区 ∉ 覆盖 → `degraded`，不编造灯 |
| 评级依据文案 | 配置模板 + 数据钩子 | `rating_rationale` 非 LLM 散文 |

Skill 提示词里可以**只读**注入评级摘要作语境，但输出契约不含评级字段；校验失败也不会改灯——只把建议降回模板。

## 画像只本机加权

六维画像（性别 / 身份 / 场景等）**永不离开服务进程**：

- 不进入 SuggestionPack，不出现在任何供应商请求体（隐私页「零上传」口径不变）。
- 只在本机对已生成的建议做确定性排序 / 加权 / 时间提示（`pipeline` 个性化前置）。
- 同区换画像：安全评级必须相等；建议可以不全相同（A5）。覆盖内有画像时，首屏可折叠对比「无画像时的建议」，无第二盏灯。

## 怎么核对

```bash
python -m pytest tests/test_g2_suggestion_path.py -q   # 本页存在且 README 可链
python -m pytest tests/test_a5_profile_local.py -q     # 画像本机、灯不变
python -m pytest tests/ -q                             # 唯一判定
```

质量数字上的两路径对照（Skill vs 模板）见 README「质量基线」与 `docs/baseline-vs-safepass.md`（N2）；本页只讲架构成长，不重抄指标表。
