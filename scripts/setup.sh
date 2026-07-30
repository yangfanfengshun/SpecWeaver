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

cursor_command() {
  if command -v agent >/dev/null 2>&1; then
    printf 'agent'
  elif command -v cursor-agent >/dev/null 2>&1; then
    printf 'cursor-agent'
  fi
}

install_codex() {
  if ! command -v codex >/dev/null 2>&1; then
    echo "Codex：未检测到 codex CLI，已跳过。"
    return 0
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
    echo "Claude Code：未检测到 claude CLI，已跳过。"
    return 0
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
  local command
  command="$(cursor_command)"
  if [[ -n "$command" ]]; then
    cat <<EOF
Cursor CLI：已检测到 $command
Cursor 插件：待人工安装

请运行：
  $command

进入 Cursor Agent 后输入 /plugin，在 Marketplace 中选择 SpecWeaver 并确认安装。
安装后重新加载 Cursor，并新建 Agent 任务验证 Skill 和 MCP。
EOF
    return
  fi
  cat <<'EOF'
Cursor：未检测到 agent 或 cursor-agent，已跳过 Cursor CLI 插件安装。

如果你使用 Cursor IDE，请按以下步骤安装：
1. 打开 Cursor 的 Agent 对话；
2. 输入：
/add-plugin https://github.com/yangfanfengshun/SpecWeaver
3. 在插件面板确认安装；
4. 执行 Developer: Reload Window；
5. 新建 Agent 任务验证 SpecWeaver Skill 和 MCP。
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
Cursor：请在 Agent 对话中重新执行：
/add-plugin https://github.com/yangfanfengshun/SpecWeaver
确认插件详情显示目标版本后，执行 Developer: Reload Window 并新建 Agent 任务。
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
  if config_value_present TOWER_COOKIE &&
    config_value_present TOWER_EMAIL &&
    config_value_present TOWER_PASSWORD; then
    tower_status="已配置（支持自动续期）"
  elif config_value_present TOWER_COOKIE; then
    tower_status="已配置（仅 Cookie）"
  fi
  if config_value_present EOLINK_BASE_URL &&
    config_value_present EOLINK_USER &&
    config_value_present EOLINK_PASSWORD; then
    eolink_status="已配置"
  fi
  if config_value_is_false LANHU_ENABLED; then
    lanhu_status="已关闭"
  elif config_value_present LANHU_COOKIE &&
    config_value_present LANHU_PHONE &&
    config_value_present LANHU_PASSWORD; then
    lanhu_status="已配置（支持自动续期）"
  elif config_value_present LANHU_COOKIE; then
    lanhu_status="已配置（仅 Cookie）"
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
  local cursor_cli
  cursor_cli="$(cursor_command)"
  if [[ -n "$cursor_cli" ]]; then
    echo "Cursor CLI：${cursor_cli}；插件版本：请在 Cursor 中人工确认"
  else
    echo "Cursor CLI：未检测到 agent 或 cursor-agent"
  fi
}

parse_host_options() {
  SELECT_CODEX=false
  SELECT_CLAUDE=false
  SELECT_CURSOR=false
  HOST_WAS_SELECTED=false

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
        # 安装和配置默认分离；保留参数只为兼容旧命令。
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

select_default_hosts() {
  if [[ "$HOST_WAS_SELECTED" == true ]]; then
    return
  fi
  SELECT_CODEX=true
  SELECT_CLAUDE=true
  SELECT_CURSOR=true
}

command_install() {
  parse_host_options "$@"
  select_default_hosts

  install_cli
  local failed=0
  local uv_bin
  uv_bin="$(find_uv)"
  if [[ -z "$uv_bin" ]]; then
    echo "未找到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/" >&2
    failed=1
  fi

  if [[ "$SELECT_CODEX" == true ]] && ! install_codex; then
    failed=1
  fi
  if [[ "$SELECT_CLAUDE" == true ]] && ! install_claude; then
    failed=1
  fi
  if [[ "$SELECT_CURSOR" == true ]]; then
    print_cursor_install
  fi

  cat <<'EOF'

SpecWeaver 安装流程已结束，认证配置尚未开始。
请在普通终端运行：
  specweaver configure

也可以只配置一个平台：
  specweaver configure tower
  specweaver configure eolink
  specweaver configure lanhu

加载提示：
- Codex：新建任务。
- Claude Code：执行 /reload-plugins，再用 /mcp 检查服务。
- Cursor：完成原生插件安装后重新加载，并新建任务。
EOF
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
    if [[ -n "$(cursor_command)" ]]; then
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
  echo "认证配置保持不变；如需更新，请运行：specweaver configure"
  command_status
  return "$failed"
}

print_help() {
  cat <<'EOF'
用法：
  specweaver install [--codex] [--claude] [--cursor] [--all]
  specweaver update [--codex] [--claude] [--cursor] [--all]
  specweaver status
  specweaver configure [tower|eolink|lanhu] [--non-interactive]
  specweaver configure tower --cookie
  specweaver check [tower|eolink|lanhu]

install 不指定宿主时默认处理 Codex、Claude Code 和 Cursor；缺少某个宿主 CLI
只跳过该宿主，不影响其他安装结果。安装和配置相互独立，安装后手动运行
specweaver configure。Cursor 插件仍需在原生界面确认。
EOF
}

case "${1:-}" in
  install)
    shift
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
      print_help
      exit 0
    fi
    command_install "$@"
    ;;
  update)
    shift
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
      print_help
      exit 0
    fi
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
