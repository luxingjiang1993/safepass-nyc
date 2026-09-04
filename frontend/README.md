# 前端薄渲染层（循环外，标准 Implement）

消费 `safepass/contracts.py` 的结构化响应契约做纯渲染，**不承载业务逻辑**（spec D1）。

## 技术选型（issue 11 开工时定）

Python 标准库 `http.server` 线程化服务 + 服务端 HTML 渲染（`frontend/render.py`
纯函数，pytest 直接断言）。**零新增依赖**，Ralph 环境不受影响；会话为进程内
cookie 载体，零持久化。

- 布局参考：PRD v2.0 §6.2 三张 ASCII 线框（首页 / 查询结果页 / 紧急模式；PRD 为课程材料已存档不随仓库分发，线框已落地为本目录实现）
- ticket 11：首页 + 查询结果渲染（五个快速查询按钮、评级、图表模块、对比/降级视图）
- ticket 12：紧急模式页 + 画像侧边栏（会话级、零持久化）

## 运行

```bash
python -m frontend.app        # http://127.0.0.1:8000
```

路由（全部薄胶水）：

| 路由 | 行为 |
|------|------|
| `GET /` | 首页：查询输入框 + 五个核心警区快速查询按钮（配置别名表驱动，零硬编码） |
| `GET /query?q=…` | 唯一接缝 `safepass.pipeline.execute_query`（llm_client=None 确定性路径，离线可跑）→ `render_result` 渲染判别联合 |
| `GET /static/style.css` | 样式（窄屏单列无横向滚动，结构层） |

会话（spec D2/D6）：cookie `safepass_sid` + 进程内 `SessionStore` 保存上轮
`SessionState`（结构化结果，不存对话历史）；降级/紧急响应经
`SessionState.from_result` 的 TypeError 契约自动清空。服务重启即全部消失。

## 渲染层不变量（tests/test_frontend_render.py + tests/test_frontend_app.py 锁定）

- 评级图标与文字并存（🟢🟡🔴⚪ 标签复用后端 `degraded.RATING_LABELS` 单一事实源），不依赖颜色
- 可信度星级 = CONTEXT.md 档位映射（表现层常量）；样本量文案动态渲染真实命中数（AC-009）
- 图表数字与契约 `charts` 字段逐字段一致；⚪ 时图表模块整体隐藏（AC-022）
- 每处分析末尾渲染免责声明；`unknowns` 区域按契约渲染（AC-007/010）
- 全部用户可见文本经 HTML 转义统一出口

UX 主观项（语气温暖、可信度感知、窄屏实机、无障碍抽验）转人工验收清单，不属于本目录的自测范围。
