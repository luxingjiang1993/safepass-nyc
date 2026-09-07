# 10 — N3 一键复现「审阅者路径」（T2-A3）

## 执行方式 / 并行组
- **方式：/ralph**（脚本 + README 一节 + 无 key 断言，机械票；前置齐全：金标子集在库、确定性路径现状可跑。headless 注意 `env -u ANTHROPIC_MODEL` + 停循环清孤儿孙进程）
- **依赖**：无
- **并行组**：槽 1，与 A1（#16）、D1（#21）三窗口并行
- **文件冲突警示**：README「本地命令」节与 B1/B2/E1 的指标/叙事节不同 hunk，可并行
- **阻塞**：无

## 来源
docs/portfolio-100-execution-plan.md §7.7 N3 + 文首补丁 P4

## 目标 / 缺口 / 做法 / DoD / 加分

- 单一命令：装依赖（或 Docker）→ 跑 5 条固定 query → 打印契约摘要 + 打开本地页。
- 明确：无 key 走确定性路径；有 key 走 Skill。
- **Windows 可跑**（作者环境是 Windows）。
- **DoD**：文档写明命令；无 key 路径全绿；与 E7 `demo_queries.py` 宜合并，避免双入口。
- **为何锁 T2**：降低「作品造假/只能作者机器跑」的先验怀疑。

## Phase 3 开赛定案（P4/P6，效力优先）

1. 本票是 P4 演示门闩 #18，波 1 收口必备。
2. 5 条固定 query 覆盖：安全 + 越界 + 紧急（P4 门槛子集），与金标子集对齐。
3. 无 key 路径 = 确定性 one_liner + 模板建议（grounds 空态打印「通用建议」），仍打印完整契约摘要。

## 允许改动
- `scripts/demo_queries.py`（或等价，与 E7 合并设计避免双入口）
- README（本地 3 命令一节：装依赖→跑 demo→开本地页）
- `tests/`（无 key 路径全绿断言）
- `docs/`（复现说明）

## 禁止
- 引入新依赖/框架
- 5 条 query 里出现真实 API key 或非 fixture 数据

## 验证
- `python -m pytest tests/ -q`
- Windows 实跑 `python scripts/demo_queries.py`（无 key 路径）

## 完成承诺
- 一条命令在 Windows 无 key 环境下跑通 5 条固定 query（安全+越界+紧急）并打印契约摘要；README 写明命令；无 key 路径测试全绿；基线全绿。
