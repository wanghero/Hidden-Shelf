#!/usr/bin/env bash
# 重启进度网页：停掉所有 shelf serve，等端口释放，再在后台起一个，确认能访问后打开浏览器。
#   用法：scripts/restart-serve.sh [端口]     默认 8031
#   日志：~/.hidden-shelf/serve.log
set -euo pipefail
PORT="${1:-8031}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${HIDDEN_SHELF_HOME:-$HOME/.hidden-shelf}/serve.log"
mkdir -p "$(dirname "$LOG")"

pkill -f "shelf serve" 2>/dev/null && echo "已停掉旧的 shelf serve" || true
for _ in $(seq 1 20); do
  lsof -iTCP:"$PORT" -sTCP:LISTEN -nP >/dev/null 2>&1 || break
  sleep 0.5
done
if lsof -iTCP:"$PORT" -sTCP:LISTEN -nP >/dev/null 2>&1; then
  echo "端口 $PORT 还被占着：" >&2; lsof -iTCP:"$PORT" -sTCP:LISTEN -nP >&2; exit 1
fi

cd "$REPO"
nohup uv run shelf serve --port "$PORT" --no-browser >"$LOG" 2>&1 &
for _ in $(seq 1 30); do
  sleep 0.5
  if curl -sf -o /dev/null "http://127.0.0.1:$PORT/"; then
    echo "进度网页已启动：http://127.0.0.1:$PORT/  （版本 $(uv run shelf --version | awk '{print $2}')）"
    echo "日志：$LOG"
    open "http://127.0.0.1:$PORT/" 2>/dev/null || true
    exit 0
  fi
done
echo "15 秒内没起来，看日志：$LOG" >&2; tail -20 "$LOG" >&2; exit 1
