# F2 Guardrail 覆盖矩阵

审阅者用这一页核对：**哪类输入走紧急 / 防线拒绝 / 诚实降级 / 覆盖内安全**，以及每条路径钉在哪条测试或金标上。

- 票：GitHub `#48` / 第三刀 F2
- 产品接缝：`execute_query`（`safepass/pipeline.py`）
- N1 注入报表（独立工件）：[`docs/n1-injection-report.md`](n1-injection-report.md)，夹具 `fixtures/eval/injection_attacks_v1.json`
- B3 对抗专表（独立工件）：[`docs/b3-adversarial-report.md`](b3-adversarial-report.md)，夹具 `fixtures/eval/adversarial_goldens_v1.json`
- 主金标 L1：`fixtures/eval/golden_set_v1.json`，断言 `tests/test_golden_set.py`

N1 与 B3 **夹具分表**：攻击集是 `injection_attacks_v1.json`，对抗金标是 `adversarial_goldens_v1.json`。两页可互相链接，用例不得并入同一 JSON。

## 约定

本页必须同时满足：四形态 `emergency` / `guardrail` / `degraded` / `safety` 各有一行；每行链到仓库内真实 pytest 函数名或金标 ID；B3 五类 `bias` / `weapon` / `panic` / `coverage_evasion` / `platitude` 有代表 ID；并链到 N1 报表页。对比追问不是第五种守卫。

管线顺序（紧急先于防线，防线先于 D12 越界）：关键词紧急 → FC 紧急第二层 → 偏见/武器静态守卫 → 覆盖判定 → 覆盖内安全查询（评级纯函数；建议校验失败则模板降级，灯仍由引擎写出）。

## 总表

| 输入类型 | 契约形态 | 判定（零 LLM 写灯） | 锚点：测试 / 金标 ID |
|---|---|---|---|
| 紧急关键词或紧急路由（抢劫、跟踪、持刀威胁等） | `emergency` | 静态紧急表组装；优先于武器守卫，避免「防身」紧急被拒绝截胡 | `test_neg008_emergency_keywords_trigger_static_branch`；`test_keyword_direct_query_triggers_emergency`；`test_emergency_layer2_not_shadowed_by_weapon_guardrail` |
| 种族/族裔偏见诱导 | `guardrail`（`bias_refusal`） | `guardrails.bias_markers` 子串命中；拒绝形态无评级字段 | `test_neg003_bias_questions_refused_with_structural_pivot`；N1-008；B3 `bias`：B3-001 … B3-010 |
| 武器/器械购买或防身器械清单 | `guardrail`（`weapon_refusal`） | `guardrails.weapon_markers`；转向合法途径，建议不含器械词 | `test_neg004_weapon_questions_refused_with_legal_paths`；N1-007；B3 `weapon`：B3-011 … B3-020 |
| 覆盖外 / 跨警区 / 未识别地点，或诱导编造越界评级 | `degraded` | D12 后置：警区 ∉ 覆盖清单 → 无数据、不编造灯 | `test_l1_out_of_coverage_degraded`；`test_out_of_coverage_query_degrades_and_uses_no_foreign_data`；G01、G02、G05；N1-009；B3 `coverage_evasion`：B3-031 … B3-040 |
| 覆盖内地点安全查询（含 Skill 被恐慌词/套话攻陷后的模板降级） | `safety` | 评级 / 可信度由 `rating_engine` 复算；恐慌与空话黑名单拒绝模型产出后仍走安全契约 | `test_l1_new_query_safety`；G25、G26；N1-001（改写评级话术 → 模板降级、灯不变）；B3 `panic`：B3-021 … B3-030；B3 `platitude`：B3-041 … B3-050 |

## B3 五类如何落入上表

| B3 类别 | 中文 | 期望形态 | 代表 ID | 对应防线 |
|---|---|---|---|---|
| `bias` | 偏见诱导 | `guardrail` | B3-001 | NEG-003 偏见静态表 |
| `weapon` | 武器/器械 | `guardrail` | B3-011 | NEG-004 武器静态表 |
| `panic` | 恐慌性夸大 | `safety` | B3-021 | NEG-006 恐慌黑名单 → 校验拒绝 → 模板建议；`rating` 仍确定性 |
| `coverage_evasion` | 越界编造评级 | `degraded` | B3-031 | D12 诚实降级 |
| `platitude` | 套话/空话建议 | `safety` | B3-041 | AC-006 空话黑名单 → 模板建议；灯不变 |

明细与负向放松见 B3 报表，不在本页重抄 50 行。N1 九条注入的分类与负向放松见 N1 报表；本矩阵只取与四形态对应的代表 ID（N1-001 / N1-007 / N1-008 / N1-009）。
