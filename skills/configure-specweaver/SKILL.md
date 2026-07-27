---
name: configure-specweaver
description: 安全配置或重新配置 SpecWeaver 的 Tower、Eolink 和蓝湖认证信息，并执行连接检查。用户要求安装后初始化、配置 SpecWeaver、只更新某个平台的 Cookie 或密码、检查数据源认证、运行 specweaver configure 时使用。
---

# 配置 SpecWeaver

## 目标

从当前已安装插件的缓存目录提供终端配置命令。首次配置只补齐缺失项；认证失效时只更新受影响的平台。不得要求用户克隆源码，也不得读取、打印或复述已有密钥。

## 执行

1. Claude Code 使用 `${CLAUDE_PLUGIN_ROOT}`，Cursor 使用 `${CURSOR_PLUGIN_ROOT}`；Codex 以当前 Skill 的已安装路径为基准向上两级解析插件根目录。不得使用用户业务仓库中的同名相对路径。
2. 如果终端还没有 `specweaver` 命令，从插件根目录运行 `scripts/setup.sh --install-cli` 安装入口；不得让用户手工修改插件缓存。
3. 首次配置运行 `specweaver configure`，只补齐缺失项。
4. 已知失效平台时只运行对应命令：`specweaver configure tower`、`specweaver configure eolink` 或 `specweaver configure lanhu`。不得让用户重填其他平台。
5. 仅检查连接时运行 `specweaver check`；也可以在末尾加平台名，只检查一个平台。
6. 让用户直接在终端向导中明文输入 Cookie、账号和密码；不要让用户把密钥发送到对话中。
7. 用户可以整体或按平台跳过配置；跳过时保留已有值、不执行该平台验证，并提示稍后使用的配置命令。
8. 三个平台在配置时只保存认证信息，不联网验证；实际使用时验证，失效则提示用户重新配置。
9. 按终端汇总说明成功、已关闭、已配置待首次使用验证、已跳过或失败的平台。验证失败时只重试失败平台。

三平台认证信息保存后标记为“已配置，待首次使用验证”；首次处理真实资源时，再由对应 MCP 检查认证信息和访问权限。

## 非交互模式

仅当用户明确要求自动化配置，并且必要环境变量已在终端环境中准备好时，运行 `specweaver configure --non-interactive`。可以在命令末尾指定单个平台；未指定时保存全部已启用平台。三平台都延迟到首次使用时验证。

## 安全边界

- 不执行 `source ~/.specweaver/.env`，不打印该文件内容。
- 不把 Cookie、密码或登录响应写入对话、日志、需求文档或 Git。
- 不修改插件缓存中的源码。
- 配置文件应位于 `~/.specweaver/.env`；设置 `SPECWEAVER_HOME` 时使用其指定目录。
