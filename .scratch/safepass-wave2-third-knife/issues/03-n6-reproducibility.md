# 03 — N6 版本钉一页

**What to build:** 审阅者一页看懂如何换机器不漂：依赖怎么锁、索引协议、embedding 标识、FAISS 路径约束、cassette / judge 指针。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/38

- [ ] 独立复现说明页存在，README 能链到它
- [ ] 写清 Python 依赖锁定方式、pickle protocol=5、embedding 模型标识、FAISS ASCII 路径、cassette/judge 版本指针
- [ ] 不把生产密钥写进该页；不重做一键复现命令
- [ ] 有测试或对账断言：关键短语 / 指针文件存在
- [ ] `python -m pytest tests/ -q` 全绿
