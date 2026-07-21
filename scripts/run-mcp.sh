#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${1:-}"

UV_BIN="$(command -v uv || true)"
for candidate in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
  if [[ -z "$UV_BIN" && -x "$candidate" ]]; then
    UV_BIN="$candidate"
  fi
done

if [[ -z "$UV_BIN" ]]; then
  echo "未找到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 127
fi

case "$SERVER" in
  tower|eolink|lanhu)
    SCRIPT="$ROOT_DIR/mcp/$SERVER/server.py"
    ;;
  *)
    echo "未知 MCP 服务：$SERVER" >&2
    exit 2
    ;;
esac

if [[ ! -f "$SCRIPT" ]]; then
  echo "MCP 启动文件不存在：$SCRIPT" >&2
  exit 2
fi

exec "$UV_BIN" run --no-project "$SCRIPT"
