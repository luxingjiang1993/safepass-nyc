#!/usr/bin/env bash
# ============================================================================
# SafePass NYC — 冒烟脚本（票 13 / M4，spec v2「部署」节）
#
# docker build → 起容器 → 首页 200 → 查询页可达（200）。
# 真机验收属人工出口标准（spec Testing Decisions），本脚本不进 pytest。
#
# 用法：
#   scripts/docker_smoke.sh              # 用默认本地端口 18000（避开开发 8000）
#   SMOKE_PORT=28000 scripts/docker_smoke.sh
# ============================================================================
set -euo pipefail

IMAGE="safepass:smoke"
CONTAINER="safepass-smoke"
PORT="${SMOKE_PORT:-18000}"
BASE_URL="http://127.0.0.1:${PORT}"

cleanup() {
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[1/4] docker build -t ${IMAGE}"
docker build -t "${IMAGE}" .

echo "[2/4] 启动容器 ${CONTAINER}（127.0.0.1:${PORT} → 8000）"
docker run -d --name "${CONTAINER}" -p "127.0.0.1:${PORT}:8000" "${IMAGE}" >/dev/null

echo "[3/4] 等待首页就绪（首轮查询需冷启动 embedding 模型，宽限 120s）"
home_code=""
for _ in $(seq 1 60); do
    home_code=$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/" || true)
    [ "${home_code}" = "200" ] && break
    sleep 2
done
if [ "${home_code}" != "200" ]; then
    echo "FAIL: 首页未在 120s 内返回 200（最后状态：${home_code:-无响应}）"
    docker logs "${CONTAINER}" 2>&1 | tail -20 || true
    exit 1
fi
echo "首页 200 OK"

echo "[4/4] 查询页可达（/query?q=法拉盛 → 走 execute_query 全管线）"
query_code=$(curl -s -o /dev/null -w '%{http_code}' \
    --get --data-urlencode "q=法拉盛" "${BASE_URL}/query")
if [ "${query_code}" != "200" ]; then
    echo "FAIL: 查询页返回 ${query_code}（期望 200）"
    docker logs "${CONTAINER}" 2>&1 | tail -20 || true
    exit 1
fi
echo "查询页 200 OK"

echo "SMOKE PASS"
