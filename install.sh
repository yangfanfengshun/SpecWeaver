#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${SPECWEAVER_REPOSITORY:-https://github.com/yangfanfengshun/SpecWeaver.git}"
SPECWEAVER_DIR="${SPECWEAVER_HOME:-$HOME/.specweaver}"
RUNTIME_DIR="${SPECWEAVER_RUNTIME_DIR:-$SPECWEAVER_DIR/runtime}"

if ! command -v git >/dev/null 2>&1; then
  echo "未找到 git，请先安装 Git。" >&2
  exit 127
fi

mkdir -p "$SPECWEAVER_DIR"
chmod 700 "$SPECWEAVER_DIR"

if [[ -e "$RUNTIME_DIR" ]]; then
  if [[ ! -d "$RUNTIME_DIR/.git" ]]; then
    echo "无法安装：$RUNTIME_DIR 已存在，但不是 SpecWeaver Git 仓库。" >&2
    exit 1
  fi

  CURRENT_ORIGIN="$(git -C "$RUNTIME_DIR" remote get-url origin 2>/dev/null || true)"
  if [[ "$CURRENT_ORIGIN" != "$REPOSITORY" ]]; then
    echo "无法更新：$RUNTIME_DIR 的 origin 不是预期仓库。" >&2
    echo "当前：${CURRENT_ORIGIN:-未配置}" >&2
    echo "预期：$REPOSITORY" >&2
    exit 1
  fi

  if [[ -n "$(git -C "$RUNTIME_DIR" status --porcelain)" ]]; then
    echo "无法更新：$RUNTIME_DIR 存在本地修改，请先处理后重试。" >&2
    exit 1
  fi

  echo "正在更新 SpecWeaver runtime..."
  git -C "$RUNTIME_DIR" pull --ff-only
else
  echo "正在安装 SpecWeaver runtime..."
  git clone --depth 1 "$REPOSITORY" "$RUNTIME_DIR"
fi

SETUP="$RUNTIME_DIR/scripts/setup.sh"
if [[ ! -x "$SETUP" ]]; then
  echo "安装包不完整：缺少可执行的 scripts/setup.sh。" >&2
  exit 1
fi

exec "$SETUP" install "$@"
