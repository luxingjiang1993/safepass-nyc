# B4：BM25-only vs 混合检索对照（mock 世界，写一次）

- **日期**：2026-09-09
- **票**：GitHub `#31` / 波 2 第二刀 B4
- **查询集**：`fixtures/eval/b4_retrieval_labels_v1.json`（20 条）
- **索引**：`fixtures/index/`（与产品同一 mock 知识库，禁止另起语料）
- **口径**：Recall@3 = 应命中文档标识是否出现在 top-3（布尔，非 nDCG）
- **BM25-only**：同一落盘索引上的关键词排序（`rank_bm25` + `scripts.build_index.tokenize`），不另建语料
- **混合检索**：`safepass.intel_agent.search`（FAISS + BM25，RRF 融合）
- **本页数字一次性写入**；默认行为基线只断言本文件存在且含可核对结论，**不在 pytest 里重算 embedding**

## 结论

| 路径 | Recall@3 | 说明 |
|------|----------|------|
| BM25-only | 20/20（100%） | 本标注集大量复用专名 + 主题词，关键词路已能召回 |
| 混合检索 | 20/20（100%） | 与 BM25-only 并列，**hybrid ≥ BM25** |
| 相对关系 | hybrid ≥ BM25 | 融合未降低标注召回 |

RRF 仍保留的原因（与 CONTEXT.md「混合检索」一致）：纯向量对精确地名/犯罪术语不稳，BM25 专名兜底；向量路承担无专名填充的语义问法。本 20 条标注上两路 Recall@3 打平，说明门闩钉的是「应命中文档进 top-3」，不是「每次融合都改写名次」。

## 逐条

命中列：1 = top-3 含应命中文档，0 = 未含。top-3 列为文档标识顺序。

| ID | 查询 | 应命中 | BM25-only 命中 | 混合检索命中 | BM25-only top-3 | 混合检索 top-3 |
|----|------|--------|----------------|--------------|-----------------|----------------|
| B4-01 | 法拉盛晚上安全吗？ | p109_overview | 1 | 1 | p109_overview, p109_emergency, p109_scam | p109_overview, p109_emergency, p109_scam |
| B4-02 | 法拉盛 换汇诈骗 | p109_scam | 1 | 1 | p109_scam, p109_overview, p109_emergency | p109_scam, p109_overview, p109_emergency |
| B4-03 | 法拉盛 中文警员 | p109_emergency | 1 | 1 | p109_overview, p109_emergency, p109_scam | p109_overview, p109_emergency, p109_scam |
| B4-04 | 法拉盛最近有什么针对华人的骗局要小心吗 | p109_scam | 1 | 1 | p109_overview, p109_scam, p5_scam | p109_overview, p109_scam, p5_scam |
| B4-05 | flushing 缅街 商业区 扒窃 | p109_overview | 1 | 1 | p109_overview, p109_scam, p109_emergency | p109_overview, p109_scam, p109_emergency |
| B4-06 | 上东区晚上安全吗？ | p19_overview | 1 | 1 | p19_overview, p19_scam, p19_emergency | p19_overview, p19_scam, p19_emergency |
| B4-07 | 上东区 仇恨犯罪 | p19_overview | 1 | 1 | p19_overview, p109_overview, p90_overview | p19_overview, p109_overview, p90_overview |
| B4-08 | 上东区 钓鱼短信 银行账户冻结 | p19_scam | 1 | 1 | p19_scam, p90_scam, p84_scam | p19_scam, p90_scam, p84_scam |
| B4-09 | 上东区夜里一个人走路回家要注意什么 | p19_overview | 1 | 1 | p19_overview, p19_scam, p19_emergency | p19_overview, p19_scam, p19_emergency |
| B4-10 | 唐人街晚上安全吗？ | p5_overview | 1 | 1 | p5_overview, p19_overview, p5_scam | p5_overview, p19_overview, p5_scam |
| B4-11 | 唐人街 冒充使领馆诈骗 | p5_scam | 1 | 1 | p5_scam, p5_overview, p19_overview | p5_scam, p5_overview, p19_overview |
| B4-12 | 唐人街 免费法律援助 | p5_emergency | 1 | 1 | p5_emergency, p109_emergency, p90_emergency | p5_emergency, p109_emergency, p90_emergency |
| B4-13 | 唐人街老人总接到奇怪的电话怎么办 | p5_scam | 1 | 1 | p5_scam, p5_overview, p5_emergency | p5_scam, p5_overview, p5_emergency |
| B4-14 | 威廉斯堡晚上安全吗？ | p90_overview | 1 | 1 | p90_overview, p90_scam, p90_emergency | p90_overview, p90_scam, p90_emergency |
| B4-15 | 威廉斯堡 租房 押金诈骗 | p90_scam | 1 | 1 | p90_scam, p84_scam, p90_overview | p90_scam, p84_scam, p90_overview |
| B4-16 | williamsburg 夜间 娱乐场所 纠纷 | p90_emergency | 1 | 1 | p90_emergency, p90_overview, p19_scam | p90_emergency, p90_overview, p19_scam |
| B4-17 | 布鲁克林高地安全吗？ | p84_overview | 1 | 1 | p84_overview, p84_emergency, p84_scam | p84_overview, p84_emergency, p84_scam |
| B4-18 | 布鲁克林高地 租房 押金 骗局 | p84_scam | 1 | 1 | p84_scam, p90_scam, p84_overview | p84_scam, p90_scam, p84_overview |
| B4-19 | 布鲁克林高地 急诊 医院 | p84_emergency | 1 | 1 | p84_emergency, p84_overview, p84_scam | p84_emergency, p84_overview, p84_scam |
| B4-20 | 布鲁克林 大桥公园 走散 集合点 | p84_emergency | 1 | 1 | p84_emergency, p84_overview, p84_scam | p84_emergency, p84_overview, p84_scam |

## 复现（人工，非默认基线）

在产品同一索引上分别取 BM25 名次与 `intel_agent.search` 名次，对照 `expected_doc_ids`。改标注或改坏 `fixtures/index` 后，先跑 `python -m pytest tests/test_b4_retrieval_regression.py -q`（应变红），需要更新本表时再手工重算并改数字。
