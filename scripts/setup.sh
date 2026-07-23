#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_REPOSITORY="yangfanfengshun/SpecWeaver"
PLUGIN_SELECTOR="specweaver@specweaver"
MARKETPLACE_NAME="specweaver"
SPECWEAVER_DIR="${SPECWEAVER_HOME:-$HOME/.specweaver}"
CONFIG_FILE="$SPECWEAVER_DIR/.env"

find_uv() {
  local uv_bin
  uv_bin="$(command -v uv || true)"
  local candidate
  for candidate in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [[ -z "$uv_bin" && -x "$candidate" ]]; then
      uv_bin="$candidate"
    fi
  done
  printf '%s' "$uv_bin"
}

install_cli() {
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
}

run_configure() {
  local uv_bin
  uv_bin="$(find_uv)"
  if [[ -z "$uv_bin" ]]; then
    echo "未找到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/" >&2
    return 127
  fi
  "$uv_bin" run --no-project "$ROOT_DIR/scripts/configure.py" "$@"
}

codex_marketplace_exists() {
  local output
  output="$(codex plugin marketplace list 2>/dev/null)" || return 1
  awk '$1 == "specweaver" { found = 1 } END { exit !found }' <<<"$output"
}

codex_plugin_installed() {
  local output
  output="$(codex plugin list --marketplace "$MARKETPLACE_NAME" 2>/dev/null)" || return 1
  grep -Eq '^specweaver@specweaver[[:space:]]+installed' <<<"$output"
}

claude_marketplace_exists() {
  local output
  output="$(claude plugin marketplace list 2>/dev/null)" || return 1
  grep -Eq '(^|[[:space:]])specweaver([[:space:]]|$)' <<<"$output"
}

claude_plugin_installed() {
  local output
  output="$(claude plugin list 2>/dev/null)" || return 1
  grep -Eq '(^|[[:space:]])specweaver@specweaver([[:space:]]|$)' <<<"$output"
}

cursor_available() {
  command -v cursor >/dev/null 2>&1 ||
    [[ -d /Applications/Cursor.app ]] ||
    [[ "${SPECWEAVER_ASSUME_CURSOR:-0}" == "1" ]]
}

install_codex() {
  if ! command -v codex >/dev/null 2>&1; then
    echo "Codex：未找到 codex 命令。" >&2
    return 1
  fi

  if ! codex_marketplace_exists; then
    echo "Codex：添加 SpecWeaver marketplace..."
    codex plugin marketplace add "$PUBLIC_REPOSITORY" || return 1
  fi
  if codex_plugin_installed; then
    echo "Codex：已安装，继续复用现有插件。"
  else
    echo "Codex：安装 SpecWeaver..."
    codex plugin add "$PLUGIN_SELECTOR" || return 1
  fi
}

install_claude() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "Claude Code：未找到 claude 命令。" >&2
    return 1
  fi

  if ! claude_marketplace_exists; then
    echo "Claude Code：添加 SpecWeaver marketplace..."
    claude plugin marketplace add "$PUBLIC_REPOSITORY" || return 1
  fi
  if claude_plugin_installed; then
    echo "Claude Code：已安装，继续复用现有插件。"
  else
    echo "Claude Code：安装 SpecWeaver..."
    claude plugin install "$PLUGIN_SELECTOR" || return 1
  fi
}

print_cursor_install() {
  cat <<'EOF'
Cursor：请在 Cursor Agent 中执行下面的命令，并在插件面板完成安装：
/add-plugin https://github.com/yangfanfengshun/SpecWeaver
安装后执行 Developer: Reload Window，并新建 Agent 任务。
EOF
}

update_codex() {
  if ! command -v codex >/dev/null 2>&1 || ! codex_plugin_installed; then
    echo "Codex：未安装 SpecWeaver，跳过更新。"
    return 0
  fi
  echo "Codex：刷新 marketplace 并更新插件..."
  codex plugin marketplace upgrade "$MARKETPLACE_NAME" || return 1
  codex plugin add "$PLUGIN_SELECTOR" || return 1
}

update_claude() {
  if ! command -v claude >/dev/null 2>&1 || ! claude_plugin_installed; then
    echo "Claude Code：未安装 SpecWeaver，跳过更新。"
    return 0
  fi
  echo "Claude Code：刷新 marketplace 并更新插件..."
  claude plugin marketplace update "$MARKETPLACE_NAME" || return 1
  claude plugin update "$PLUGIN_SELECTOR" || return 1
}

print_cursor_update() {
  cat <<'EOF'
Cursor：请在 Customize 或 Plugins 中对 specweaver 执行 Update 或 Reinstall，
然后执行 Developer: Reload Window 并新建 Agent 任务。
EOF
}

current_version() {
  sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' \
    "$ROOT_DIR/.codex-plugin/plugin.json" | head -n 1
}

codex_installed_version() {
  local output
  output="$(codex plugin list --marketplace "$MARKETPLACE_NAME" 2>/dev/null)" || return 1
  awk '
    $1 == "specweaver@specweaver" {
      for (i = 1; i <= NF; i++) {
        if ($i ~ /^[0-9]+[.][0-9]+[.][0-9]+$/) {
          print $i
          exit
        }
      }
    }
  ' <<<"$output"
}

claude_installed_version() {
  local output
  output="$(claude plugin list 2>/dev/null)" || return 1
  awk '
    /specweaver@specweaver/ { found = 1; next }
    found && /Version:/ { print $2; exit }
  ' <<<"$output"
}

config_value_present() {
  local key="$1"
  awk -F= -v key="$key" '
    $1 == key {
      value = substr($0, index($0, "=") + 1)
      exit(value == "" || value == "''" || value == "\"\"")
    }
    END {
      if (!value) exit 1
    }
  ' "$CONFIG_FILE"
}

config_value_is_false() {
  local key="$1"
  awk -F= -v key="$key" '
    $1 == key {
      value = tolower(substr($0, index($0, "=") + 1))
      gsub(/^['\''"]|['\''"]$/, "", value)
      exit(value == "false" ? 0 : 1)
    }
    END {
      if (!value) exit 1
    }
  ' "$CONFIG_FILE"
}

print_config_status() {
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "配置：未配置"
    return
  fi

  local tower_status="缺失"
  local eolink_status="缺失"
  local lanhu_status="缺失"
  if config_value_present TOWER_COOKIE; then
    tower_status="已配置"
  fi
  if config_value_present EOLINK_BASE_URL &&
    config_value_present EOLINK_USER &&
    config_value_present EOLINK_PASSWORD; then
    eolink_status="已配置"
  fi
  if config_value_is_false LANHU_ENABLED; then
    lanhu_status="已关闭"
  elif config_value_present LANHU_COOKIE; then
    lanhu_status="已配置"
  fi
  echo "配置：Tower ${tower_status}；Eolink ${eolink_status}；蓝湖 ${lanhu_status}"
}

command_status() {
  echo "SpecWeaver runtime：$(current_version)"
  local cli_path="${SPECWEAVER_BIN_DIR:-$HOME/.local/bin}/specweaver"
  if [[ -L "$cli_path" ]]; then
    echo "CLI：$cli_path -> $(readlink "$cli_path")"
  elif [[ -e "$cli_path" ]]; then
    echo "CLI：$cli_path 已存在，但不是符号链接"
  else
    echo "CLI：未安装"
  fi
  print_config_status

  local version
  if command -v codex >/dev/null 2>&1 && version="$(codex_installed_version)" &&
    [[ -n "$version" ]]; then
    echo "Codex：$version"
  else
    echo "Codex：未安装"
  fi
  if command -v claude >/dev/null 2>&1 && version="$(claude_installed_version)" &&
    [[ -n "$version" ]]; then
    echo "Claude Code：$version"
  else
    echo "Claude Code：未安装"
  fi
  if cursor_available; then
    echo "Cursor：请在插件面板确认当前版本"
  else
    echo "Cursor：未检测到"
  fi
}

parse_host_options() {
  SELECT_CODEX=false
  SELECT_CLAUDE=false
  SELECT_CURSOR=false
  HOST_WAS_SELECTED=false
  NO_CONFIGURE=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --codex|codex)
        SELECT_CODEX=true
        HOST_WAS_SELECTED=true
        ;;
      --claude|claude)
        SELECT_CLAUDE=true
        HOST_WAS_SELECTED=true
        ;;
      --cursor|cursor)
        SELECT_CURSOR=true
        HOST_WAS_SELECTED=true
        ;;
      --no-configure)
        NO_CONFIGURE=true
        ;;
      --all)
        SELECT_CODEX=true
        SELECT_CLAUDE=true
        SELECT_CURSOR=true
        HOST_WAS_SELECTED=true
        ;;
      *)
        echo "未知参数：$1" >&2
        return 2
        ;;
    esac
    shift
  done
}

select_detected_hosts() {
  if [[ "$HOST_WAS_SELECTED" == true ]]; then
    return
  fi
  if command -v codex >/dev/null 2>&1; then
    SELECT_CODEX=true
  fi
  if command -v claude >/dev/null 2>&1; then
    SELECT_CLAUDE=true
  fi
  if cursor_available; then
    SELECT_CURSOR=true
  fi
}

command_install() {
  parse_host_options "$@"
  select_detected_hosts

  local uv_bin
  uv_bin="$(find_uv)"
  if [[ -z "$uv_bin" ]]; then
    echo "未找到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/" >&2
    return 127
  fi
  if [[ "$SELECT_CODEX" == false && "$SELECT_CLAUDE" == false &&
    "$SELECT_CURSOR" == false ]]; then
    echo "没有检测到 Codex、Claude Code 或 Cursor。" >&2
    return 1
  fi

  install_cli
  local failed=0
  if [[ "$SELECT_CODEX" == true ]] && ! install_codex; then
    failed=1
  fi
  if [[ "$SELECT_CLAUDE" == true ]] && ! install_claude; then
    failed=1
  fi
  if [[ "$SELECT_CURSOR" == true ]]; then
    print_cursor_install
  fi

  if [[ "$NO_CONFIGURE" == false ]]; then
    run_configure configure || failed=1
  else
    echo "已跳过认证配置；稍后运行：specweaver configure"
  fi

  echo "安装流程完成。Codex 请新建任务；Claude Code 请执行 /reload-plugins。"
  return "$failed"
}

update_runtime() {
  if [[ "${SPECWEAVER_SKIP_RUNTIME_UPDATE:-0}" == "1" ||
    "${SPECWEAVER_UPDATE_REEXEC:-0}" == "1" ||
    ! -d "$ROOT_DIR/.git" ]]; then
    return
  fi
  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
    echo "无法更新 runtime：存在本地修改，请先处理后重试。" >&2
    return 1
  fi
  git -C "$ROOT_DIR" pull --ff-only
}

command_update() {
  parse_host_options "$@"

  if [[ "${SPECWEAVER_SKIP_RUNTIME_UPDATE:-0}" != "1" &&
    ! -d "$ROOT_DIR/.git" ]]; then
    echo "当前 specweaver 命令不由统一 runtime 管理，不能执行统一更新。" >&2
    echo "请先按 README 运行一条命令安装，或继续使用宿主原生更新方式。" >&2
    return 1
  fi

  if [[ "${SPECWEAVER_UPDATE_REEXEC:-0}" != "1" &&
    "${SPECWEAVER_SKIP_RUNTIME_UPDATE:-0}" != "1" &&
    -d "$ROOT_DIR/.git" ]]; then
    update_runtime
    SPECWEAVER_UPDATE_REEXEC=1 exec "$ROOT_DIR/scripts/setup.sh" update "$@"
  fi

  if [[ "$HOST_WAS_SELECTED" == false ]]; then
    if command -v codex >/dev/null 2>&1 && codex_plugin_installed; then
      SELECT_CODEX=true
    fi
    if command -v claude >/dev/null 2>&1 && claude_plugin_installed; then
      SELECT_CLAUDE=true
    fi
    if cursor_available; then
      SELECT_CURSOR=true
    fi
  fi

  local failed=0
  if [[ "$SELECT_CODEX" == true ]] && ! update_codex; then
    failed=1
  fi
  if [[ "$SELECT_CLAUDE" == true ]] && ! update_claude; then
    failed=1
  fi
  if [[ "$SELECT_CURSOR" == true ]]; then
    print_cursor_update
  fi
  install_cli
  if [[ "$NO_CONFIGURE" == false ]]; then
    run_configure configure || failed=1
  fi
  command_status
  return "$failed"
}

print_help() {
  cat <<'EOF'
用法：
  specweaver install [--codex] [--claude] [--cursor] [--no-configure]
  specweaver update [--codex] [--claude] [--cursor] [--no-configure]
  specweaver status
  specweaver configure [tower|eolink|lanhu]
  specweaver check [tower|eolink|lanhu]

不指定宿主时，install 处理本机检测到的宿主，update 处理已安装的宿主。
Cursor 的安装、更新和卸载仍需要在 Cursor 原生插件界面确认。
EOF
}

case "${1:-}" in
  install)
    shift
    command_install "$@"
    ;;
  update)
    shift
    command_update "$@"
    ;;
  status)
    shift
    if [[ $# -gt 0 ]]; then
      echo "status 不接受额外参数。" >&2
      exit 2
    fi
    command_status
    ;;
  help|--help|-h)
    print_help
    ;;
  --install-cli)
    shift
    if [[ $# -gt 0 ]]; then
      echo "--install-cli 不接受额外参数。" >&2
      exit 2
    fi
    install_cli
    ;;
  --configure|configure)
    install_cli
    run_configure "$@"
    ;;
  check|"")
    run_configure "$@"
    ;;
  *)
    run_configure "$@"
    ;;
esac
