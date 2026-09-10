# 安全查询结果契约字段说明（E2）

产品没有服务型 HTTP API，因此**不做**路径版本段、协商头这类服务型 API 版本号体系。
对外契约仍是进程内 `execute_query` → `ResponseContract`（见 `safepass/contracts.py`）。
本页只记录「这一阶段增了什么、语义什么时候算稳定、前端怎么兼容」，避免多了一个字段没人知道。

字段变更时改本页对应行，并同步 `safepass/contracts.py` 上该字段的注释。不要为此新开一套版本协商协议。

## 本刀相关字段

| 字段 / 展示 | 状态 | 形态 | 说明 |
|-------------|------|------|------|
| `rating_rationale` | 已稳定（第二刀 C1a） | 仅覆盖内 `SafetyQueryResult` | 确定性「评级依据」人话；四档非空。不进 Skill 输出，不进 `suggestion_grounds`。对比 / 紧急 / 防线 / 越界降级契约无此字段。 |
| 时段桶（契约名 `time_bucket`） | 本刀 C2 | 覆盖内 `SafetyQueryResult` | 能解析钟点则该桶（清晨 / 日间 / 晚间 / 深夜）；不能解析则字段缺省、仍用昼夜合计。该桶样本低于配置门槛 → `unknowns`，不编造。安全评级仍是全年 per-100k 相对全市，不按时段改灯。无钟点时不得把昼夜合计假装成「已切桶」。前端只认已声明字段，不得用桶计数冒充 `suggestion_grounds`。 |
| 中文罪名展示（`OffenseCount.label_zh`） | 本刀 C3 | Top5 与建议共用 | 映射只在 `one_liner.type_names`。未映射类型外显 `one_liner.unknown_offense_label`（「其他」），`count` 保留。无运行时翻译 API。展示与建议数据包用 `label_zh`；不要把未映射的英文法律名当成「有依据」。 |

工程师调试块（N5，`?debug=1`）上的路由意图、检索文档标识、时段桶名等**不进入** `SafetyQueryResult` 序列化，前端不得把调试键当成产品依据。

## 前端兼容策略

渲染层只读取本页与 `contracts.py` 已点名的属性。多出来的键：

1. **不得崩**：解析侧忽略未知键（Pydantic 默认忽略 extra）；渲染侧不按 `model_dump()` 全量遍历出 HTML。
2. **不得假装有依据**：建议依据槽只看 `suggestion_grounds`。该列表为空时标明「通用建议」，禁止用未知字段、图表数字、罪名中文、时段桶或 `rating_rationale` 冒充建议出处。
3. **缺字段当无**：`label_zh` 缺省时沿用 `offense_type` 字符串，不编造。`time_bucket` 缺省（无钟点）时沿用昼夜合计，不假装已切桶。

未知契约形态（`type` 不是五种判别联合之一）仍应明确失败，不静默当成安全结果页。
