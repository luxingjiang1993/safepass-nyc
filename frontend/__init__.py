"""前端首页。

首页薄渲染层入口（issue 11）：技术选型 = Python 标准库 http.server +
服务端 HTML 渲染（零新增依赖；渲染函数在 frontend/render.py，是纯函数、
pytest 直接断言）。业务逻辑一律在后端唯一接缝 safepass.pipeline.execute_query。
"""

from frontend import app

__all__ = ["app"]
