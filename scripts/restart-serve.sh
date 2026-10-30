#!/usr/bin/env bash
# 重启进度网页：停掉所有 shelf serve，等端口释放，再在后台起一个，确认能访问后打开浏览器。
#   用法：scripts/restart-serve.sh [端口]     默认 8031
#   日志：~/.hidden-shelf/serve.log
set -euo pipefail
PORT="${1:-8031}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${HIDDEN_SHELF_HOME:-$HOME/.hidden-shelf}/serve.log"
mkdir -p "$(dirname "$LOG")"

# 先看代码是不是最新的：落后 origin/main 就拉下来并装依赖；云端分支有更高版本还没合并就提醒。
cd "$REPO"
if git fetch -q origin 2>/dev/null; then
  LOCAL_VER=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] && git merge-base --is-ancestor HEAD origin/main; then
    echo "本地落后 origin/main，正在更新…"
    git pull -q --ff-only origin main && uv sync -q
    echo "已更新：v${LOCAL_VER} → v$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)"
  else
    echo "代码已是最新（v${LOCAL_VER}）"
  fi
  MAIN_VER=$(git show origin/main:pyproject.toml | grep -m1 '^version' | cut -d'"' -f2)
  for b in $(git branch -r --list 'origin/claude/*'); do
    BV=$(git show "$b:pyproject.toml" 2>/dev/null | grep -m1 '^version' | cut -d'"' -f2 || true)
    [ -n "$BV" ] && [ "$(printf '%s\n%s\n' "$MAIN_VER" "$BV" | sort -V | tail -1)" = "$BV" ] && [ "$BV" != "$MAIN_VER" ] \
      && echo "提醒：云端分支 ${b#origin/} 已到 v${BV}，还没合并进 main（gh pr list 看看）"
  done
else
  echo "连不上 GitHub，跳过版本检查"
fi

pkill -f "shelf serve" 2>/dev/null && echo "已停掉旧的 shelf serve" || true
# 等到端口真的能绑上为止（刚停掉的进程会让端口在 TIME_WAIT 里再占几秒，lsof 看不出来）。
port_free() { python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1)
try: s.bind(('127.0.0.1', $PORT))
except OSError: sys.exit(1)
finally: s.close()"; }
for _ in $(seq 1 40); do
  port_free && break
  sleep 0.5
done
if ! port_free; then
  echo "端口 $PORT 等了 20 秒还被占着：" >&2; lsof -iTCP:"$PORT" -nP >&2 || true; exit 1
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
