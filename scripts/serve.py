"""生产/容器入口（票 13 / M4）：绑 0.0.0.0 起前端服务。

frontend.app.main 默认绑 127.0.0.1（开发回环语义）；容器内必须对外监听，
故单设此入口而不改开发默认。固定绑 0.0.0.0:8000（与 Dockerfile EXPOSE /
HEALTHCHECK 一致，由 tests/test_dockerfile.py 的端口一致性断言锁定）；
需要换端口时改容器端口映射（docker run -p <host>:8000），不动入口。

生产 LLM 接线（票 12 / M4）：容器内经 env（LLM_API_KEY/LLM_BASE_URL/
LLM_MODEL）注入 DeepSeek 客户端——构造唯一注入点在
safepass.llm_wiring.build_llm_client_from_env，产出必经票 06 成本熔断器
包装；env 任一缺失 → None，走确定性路径（启动日志明示，不静默）。
"""

from __future__ import annotations

from safepass import config_loader, llm_wiring
from frontend.app import create_server

HOST = "0.0.0.0"
PORT = 8000


def main() -> None:
    # env 三变量齐全 → 真实客户端（必经熔断器）；缺失 → 确定性路径（票 12）
    llm_client = llm_wiring.build_llm_client_from_env(config_loader.get_config())
    server = create_server(host=HOST, port=PORT, llm_client=llm_client)
    mode = "生产 LLM 已接线（经成本熔断器）" if llm_client is not None else "确定性路径（未注入 LLM）"
    print(f"SafePass NYC 前端：http://{HOST}:{PORT}（{mode}，Ctrl+C 停止）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
