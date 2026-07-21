---
name: configure-specweaver
description: 安全配置或重新配置 SpecWeaver 的 Tower、Eolink 和蓝湖认证信息，并执行连接验证。用户要求安装后初始化、配置 SpecWeaver、更新失效的 Cookie 或密码、检查数据源认证、运行 setup.sh 时使用。
---

# 配置 SpecWeaver

## 目标

从当前已安装插件的缓存目录运行配置向导。不得要求用户克隆源码，也不得读取、打印或复述已有密钥。

## 执行

1. Claude Code 使用 `${CLAUDE_PLUGIN_ROOT}`，Cursor 使用 `${CURSOR_PLUGIN_ROOT}`；Codex 以当前 Skill 的已安装路径为基准向上两级解析插件根目录。不得使用用户业务仓库中的同名相对路径。
2. 首次配置或更新认证时，在可交互终端运行插件根目录下的 `scripts/setup.sh --configure`。
3. 让用户直接在终端向导中输入 Cookie、账号和密码；不要让用户把密钥发送到对话中。
4. 等待向导完成，按其汇总结果说明哪些数据源验证成功、关闭或失败。
5. 验证失败时，只说明对应平台与恢复方式，不输出配置值。用户修正后从配置步骤重试。

## 非交互模式

仅当用户明确要求自动化配置，并且必要环境变量已在终端环境中准备好时，运行 `scripts/setup.sh --non-interactive`。蓝湖启用时还需要临时提供 `LANHU_CHECK_URL` 进行真实项目权限验证。

## 安全边界

- 不执行 `source ~/.specweaver/.env`，不打印该文件内容。
- 不把 Cookie、密码或登录响应写入对话、日志、需求文档或 Git。
- 不修改插件缓存中的源码。
- 配置文件应位于 `~/.specweaver/.env`；设置 `SPECWEAVER_HOME` 时使用其指定目录。
