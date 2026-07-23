#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

INSTALL_CLI=false
CONFIGURE_ARGS=()
for argument in "$@"; do
  if [[ "$argument" == "--install-cli" ]]; then
    INSTALL_CLI=true
  else
    if [[ "$argument" == "--configure" || "$argument" == "configure" ]]; then
      INSTALL_CLI=true
    fi
    CONFIGURE_ARGS+=("$argument")
  fi
done

if [[ "$INSTALL_CLI" == true ]]; then
  BIN_DIR="${SPECWEAVER_BIN_DIR:-$HOME/.local/bin}"
  CLI_PATH="$BIN_DIR/specweaver"
  CLI_SOURCE="$ROOT_DIR/scripts/specweaver"

  mkdir -p "$BIN_DIR"
  if [[ -L "$CLI_PATH" ]]; then
    EXISTING_TARGET="$(readlink "$CLI_PATH")"
    if [[ "$EXISTING_TARGET" != */scripts/specweaver ]]; then
      echo "无法安装命令：$CLI_PATH 已指向其他程序。" >&2
      echo "请先确认该链接用途，或通过 SPECWEAVER_BIN_DIR 指定其他目录。" >&2
      exit 1
    fi
  elif [[ -e "$CLI_PATH" ]]; then
    echo "无法安装命令：$CLI_PATH 已存在且不是符号链接。" >&2
    echo "请先确认该文件用途，或通过 SPECWEAVER_BIN_DIR 指定其他目录。" >&2
    exit 1
  fi
  ln -sfn "$CLI_SOURCE" "$CLI_PATH"
  echo "已安装 SpecWeaver 命令：$CLI_PATH"
  if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "提示：$BIN_DIR 当前不在 PATH 中，请将其加入 shell 配置。" >&2
  fi
fi

if [[ ${#CONFIGURE_ARGS[@]} -eq 0 ]]; then
  exit 0
fi

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

exec "$UV_BIN" run --no-project "$ROOT_DIR/scripts/configure.py" "${CONFIGURE_ARGS[@]}"
