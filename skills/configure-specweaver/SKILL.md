---
name: configure-specweaver
description: 安全配置或重新配置 SpecWeaver 的 Tower、Eolink 和蓝湖认证信息，并执行连接检查。用户要求安装后初始化、配置 SpecWeaver、更新 Tower/蓝湖账号密码或 Cookie、只更新某个平台、检查数据源认证、运行 specweaver configure 时使用。
---

# 配置 SpecWeaver

## 目标

从当前已安装插件的缓存目录提供终端配置命令。安装和配置是独立阶段；认证失效时只更新受影响的平台。不得要求用户克隆源码，也不得读取、打印或复述已有密钥。

## 执行

1. Claude Code 使用 `${CLAUDE_PLUGIN_ROOT}`，Cursor 使用 `${CURSOR_PLUGIN_ROOT}`；Codex 以当前 Skill 的已安装路径为基准向上两级解析插件根目录。不得使用用户业务仓库中的同名相对路径。
2. 如果终端还没有 `specweaver` 命令，从插件根目录运行 `scripts/setup.sh --install-cli` 安装入口；不得让用户手工修改插件缓存。
3. 首次配置运行 `specweaver configure`，让用户在终端多选本次要处理的平台。
4. 已知失效平台时只运行对应命令：`specweaver configure tower`、`specweaver configure eolink` 或 `specweaver configure lanhu`。不得让用户重填其他平台。
5. 仅检查连接时运行 `specweaver check`；也可以在末尾加平台名，只检查一个平台。
6. 让用户直接在终端向导中输入认证信息；密码不回显，不要让用户把密钥发送到对话中。
7. Tower 普通配置输入邮箱密码，立即执行一次网页登录并生成 Cookie；失败不得覆盖旧配置，也不得自动重复提交密码。
8. 蓝湖普通配置输入手机号/邮箱和密码，立即执行网页登录、兑换正式 Cookie 并保存；失败不得覆盖旧配置，也不得自动重复提交密码。
9. Tower 或蓝湖要求验证码、人机验证、二次验证或网页流程不兼容时，输出配置文件绝对路径、对应的 `TOWER_COOKIE` / `LANHU_COOKIE` 字段，并提示 `specweaver configure <platform> --cookie`；人工入口只保存 Cookie、后验证。
10. Eolink 配置只保存认证信息，不联网验证；实际使用时验证。
11. 未选择、返回或退出时保留已有值。按终端汇总说明成功、已关闭、已配置待首次使用验证、已返回或失败的平台。

Tower 和蓝湖成功状态必须是“登录验证成功”；Eolink 保存后标记为“已配置，待首次使用验证”。

## 非交互模式

仅当用户明确要求自动化配置，并且必要环境变量已在终端环境中准备好时，运行 `specweaver configure --non-interactive`。Tower 普通模式需要 `TOWER_EMAIL` 和 `TOWER_PASSWORD`；蓝湖普通模式需要 `LANHU_PHONE` 和 `LANHU_PASSWORD`，两者都执行一次真实登录。Cookie 兜底使用对应的 `specweaver configure <platform> --cookie --non-interactive` 和 Cookie 变量。Eolink 仍延迟到首次使用时验证。

## 安全边界

- 不执行 `source ~/.specweaver/.env`，不打印该文件内容。
- 不把 Cookie、密码或登录响应写入对话、日志、需求文档或 Git。
- 不修改插件缓存中的源码。
- 配置文件应位于 `~/.specweaver/.env`；设置 `SPECWEAVER_HOME` 时使用其指定目录。
