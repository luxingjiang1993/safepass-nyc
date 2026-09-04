# 08 — 隐私页 + 免责页

**What to build:** 前端新增两个公开页面：隐私页（画像零持久化、零上传、会话随进程消失——与既有画像防线口径一致）与免责页（数据口径、免责声明、紧急资源）。继续 stdlib http.server + 服务端渲染，零新依赖。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M3 信任 + 用户（spec v2）

- [ ] 两页面路由可访问，内容口径与 ADR-0002 / 既有画像防线一致
- [ ] 沿用既有渲染/快照测试模式，测试进基线且全绿
- [ ] 零新依赖；目录快照断言不破（无意外磁盘写入）
