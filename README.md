# SpecWeaver

需求编织器，把 Tower、蓝湖和 Eolink 中分散的上下文编织成可追溯、可执行的需求资料。

> Weave scattered context into actionable specs.

本仓库根目录就是可安装的 SpecWeaver 插件。平台安装后直接从自身缓存运行，
不会在执行期间再次从 GitHub 下载 MCP 源码。

## 能力

- 读取 Tower 分类、正文、全部评论、子任务与附件；
- `BUG管理` 自动快速分析，普通需求可选择快速分析或完整资料收集；
- 完整模式按需读取蓝湖设计稿和 Eolink API，生成 `requirement.md`、`api.md` 与本地图片证据；
- 蓝湖 MCP 只使用 HTTP，不依赖上游 MCP、Playwright 或 Chromium；
- 认证失效时区分未配置、能力关闭、登录失效、无权限和网络错误，并允许更新后从失败节点重试；
- 通过 Git 提交 Skill 生成受控的 Conventional Commit，并在用户确认后向关联 Tower 写入去重评论。

## 运行要求

- macOS 或 Linux；Windows 建议使用 WSL；
- Git；
- Python 3.10～3.13；
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)；
- Codex、Claude Code 或 Cursor 之一；
- 可访问 Tower、Eolink，以及启用设计能力时的蓝湖。

MCP 依赖由 `uv` 根据入口脚本声明准备，插件目录不维护 `.venv`。

## 安装与首次配置

首次使用需要完成“安装、终端配置、重新加载、首次使用验证”。多个 AI 宿主共用
同一份 runtime、终端命令和认证配置，不需要分别填写 Tower、Eolink 或蓝湖信息。

### 1. 安装前准备

- 确认终端可以执行 `git --version` 和 `uv --version`；
- 确认可以访问 GitHub；插件从公开发布仓库安装，不需要私有开发仓库权限；
- 在浏览器中登录需要使用的 Tower 和蓝湖账号；
- 准备 Eolink 根地址、登录账号和密码。

Tower 和蓝湖的 Cookie 获取方式：

1. 打开浏览器开发者工具的 Network 面板；
2. 刷新 Tower 或蓝湖页面；
3. 选择一个发往对应域名的请求；
4. 从 Request Headers 中复制完整的 Cookie；
5. Cookie 只粘贴到后续的终端配置向导，不要发送到 Agent 对话中。

### 2. 推荐：一条命令安装

在普通终端执行：

```bash
curl -fsSL \
  https://raw.githubusercontent.com/yangfanfengshun/SpecWeaver/master/install.sh |
  bash
```

安装器会把公开发布仓库克隆到 `~/.specweaver/runtime`，检测本机的 Codex、
Claude Code 和 Cursor，复用已存在的安装，并只运行一次认证配置。它不会创建
第二套 Codex 或 Claude Code 插件，也不会修改插件缓存中的源码。

只处理指定宿主时，将参数传给安装器：

```bash
curl -fsSL \
  https://raw.githubusercontent.com/yangfanfengshun/SpecWeaver/master/install.sh |
  bash -s -- --codex
```

可将 `--codex` 替换成 `--claude` 或 `--cursor`。多个参数可以同时使用。默认
安装入口位于 `~/.local/bin/specweaver`；如果该目录不在 `PATH` 中，安装器会
明确提示。

Cursor 当前没有经过验证的非交互式插件安装命令。检测到 Cursor 或显式指定
`--cursor` 时，安装器会完成公共终端入口与认证配置，再提示在 Cursor Agent 中执行：

```text
/add-plugin https://github.com/yangfanfengshun/SpecWeaver
```

随后在插件面板完成安装。安装器不会绕过 Cursor 的确认或组织策略。

如果不希望直接执行网络脚本，可以先下载并检查：

```bash
curl -fsSL \
  https://raw.githubusercontent.com/yangfanfengshun/SpecWeaver/master/install.sh \
  -o specweaver-install.sh
less specweaver-install.sh
bash specweaver-install.sh
```

确认完成后可以删除下载的脚本。

### 3. 首次配置

推荐安装命令已经自动启动配置向导。主动跳过或非交互环境安装后，可以补充运行：

```bash
specweaver configure
```

首次配置只询问缺失项：

1. Tower Cookie；
2. Eolink 根地址、账号和密码；
3. 是否启用蓝湖设计稿能力；
4. 启用蓝湖时填写蓝湖 Cookie。

安装和配置不要求蓝湖项目链接。由于蓝湖可靠的权限检查依赖具体项目，Cookie 保存
后会显示“已配置，待首次使用验证”；第一次读取真实设计稿时，再同时检查 Cookie
和该项目的访问权限。

Cookie 和密码采用隐藏输入，不会显示在终端中。Tower 与 Eolink 会立即执行连接
验证；验证失败时只重新填写失败的平台。

配置保存到：

```text
~/.specweaver/.env
```

配置文件使用原子替换写入并设置为 `600` 权限。不要把该文件加入 Git，也不要在
Agent 对话中粘贴 Cookie、密码或文件内容。

### 4. 加载插件

安装和配置完成后，让客户端重新加载插件：

- Codex：新建一个 Agent 任务；
- Claude Code：在交互会话中执行 `/reload-plugins`；如果当前版本不支持该命令，
  再新建会话或重启 Claude Code；
- Cursor：执行 `Developer: Reload Window`，然后新建一个 Agent 任务。

### 5. 验证安装结果

在 Agent 任务中发送一个自己有权访问的 Tower 任务链接：

```text
整理这个 Tower 任务：https://tower.im/teams/<team-id>/todos/<todo-id>
```

插件能够读取任务并给出后续选项，说明安装、配置和 MCP 加载均已完成。

### 手动分平台安装

现有安装方式继续保留，适合只使用一个平台或排查统一安装器。

#### Codex

下面的代码块可以整段复制到终端；只有前一步成功才会继续：

```bash
codex plugin marketplace add yangfanfengshun/SpecWeaver && \
codex plugin add specweaver@specweaver && \
~/.codex/plugins/cache/specweaver/specweaver/0.5.1/scripts/setup.sh --configure
```

Codex 的更新、重新安装、新任务加载和故障处理规则见
[`AGENTS.md`](./AGENTS.md)。

#### Claude Code

```bash
claude plugin marketplace add yangfanfengshun/SpecWeaver && \
claude plugin install specweaver@specweaver && \
~/.claude/plugins/cache/specweaver/specweaver/0.5.1/scripts/setup.sh --configure
```

Claude Code 的更新、重载和故障处理规则见 [`CLAUDE.md`](./CLAUDE.md)。

#### Cursor

在 Cursor Agent 中执行：

```text
/add-plugin https://github.com/yangfanfengshun/SpecWeaver
```

然后从导入的 marketplace 中安装 `specweaver`。详细规则见
[`rules/specweaver.mdc`](./rules/specweaver.mdc)。

以上固定缓存路径已在 macOS 验证。Windows 路径尚未验证；Windows 建议使用 WSL，
或回到对应客户端让 AI 定位插件并启动配置。

### 安装状态与更新

查看 runtime、终端入口、配置完整性和宿主版本：

```bash
specweaver status
```

统一更新 runtime 和已安装的 Codex、Claude Code 插件：

```bash
specweaver update
```

该命令只适用于通过推荐入口创建的 `~/.specweaver/runtime`。只使用过手动分平台安装
时，先运行推荐安装命令接管，或者继续使用对应宿主的原生更新命令。

Cursor 会收到 Update 或 Reinstall 提示，仍由用户在原生插件界面确认。更新不会
覆盖 `~/.specweaver/.env`；runtime 存在本地修改时会停止，不自动覆盖。

只更新指定宿主：

```bash
specweaver update --codex
specweaver update --claude
specweaver update --cursor
```

卸载继续使用 Codex、Claude Code 或 Cursor 自身的插件管理器。首版不提供统一卸载，
避免在无法可靠确认 Cursor 状态时误删多个宿主共用的认证配置。

### 重新配置、更新认证或检查连接

某个平台认证失效时，只更新该平台，不重新询问其他配置：

```bash
specweaver configure tower
specweaver configure eolink
specweaver configure lanhu
```

检查全部或单个平台的状态：

```bash
specweaver check
specweaver check tower
```

`specweaver configure` 不带平台名时只补齐缺失项；已有配置会原样保留。更新成功后
从原流程的失败节点重试即可。

如需更换配置目录，请在启动客户端前设置 `SPECWEAVER_HOME`。

### 自动化环境

自动化环境可预先设置下列变量后运行
`specweaver configure --non-interactive`。追加平台名时只要求该平台的变量，例如
`specweaver configure tower --non-interactive`：

| 变量 | 必需条件 | 用途 |
| --- | --- | --- |
| `TOWER_COOKIE` | 始终 | 读取 Tower 与按确认发布评论 |
| `EOLINK_BASE_URL` | 始终 | Eolink 站点根地址 |
| `EOLINK_USER` | 始终 | Eolink 登录账号 |
| `EOLINK_PASSWORD` | 始终 | Eolink 登录密码 |
| `LANHU_ENABLED` | 始终 | 只接受 `true` 或 `false` |
| `LANHU_COOKIE` | 蓝湖启用时 | 读取设计稿与原图 |
| `LANHU_CHECK_URL` | 可选 | 提前检查指定蓝湖项目权限，不写入配置 |

旧配置缺少 `LANHU_ENABLED` 时按 `true` 处理。设置为 `false` 后，需求流程不会询问、读取或下载蓝湖资料。

## 使用

### 收集 Tower 需求

```text
整理这个 Tower 任务：https://tower.im/teams/<team-id>/todos/<todo-id>
```

普通需求会先展示已发现的设计稿与 API 状态，再让用户选择：

- 快速分析：只分析 Tower，在对话中回答，不生成文件；
- 完整资料收集：确认资料范围后再下载并生成文档。

提交当前改动时可以说：

```text
使用 SpecWeaver 提交当前改动
```

Git Skill 不会自动推送、创建 PR、合并或发布。Tower 评论始终先 dry-run，只有用户明确确认后才发布。

### 配置或恢复数据源

也可以让 Agent 调用同一套受控配置命令：

```text
配置 SpecWeaver
```

```text
更新 SpecWeaver 的 Tower Cookie
```

```text
检查 SpecWeaver 数据源连接
```

Agent 会调用插件自带的配置脚本。认证值只应输入终端中的隐藏输入框，不应
粘贴到聊天窗口。

## 认证失效

当 Tower、Eolink 或蓝湖认证失效时，插件会暂停依赖该平台的步骤并提示对应的
`specweaver configure <platform>` 命令。只更新失效平台并从失败节点重试，不需要
重跑安装或重填其他平台。

- Tower 失效：暂停整个流程；
- 蓝湖失效：更新后重试，或明确确认本次不采用设计稿；
- Eolink 失效：更新后重试，或明确确认本次不采用 API；
- 不输出 Cookie、密码或登录响应。

## 技术标识

- 插件 ID：`specweaver`
- 配置与数据目录：`~/.specweaver`
- 自定义目录变量：`SPECWEAVER_HOME`
- MCP：`specweaver-tower`、`specweaver-eolink`、`specweaver-lanhu`

## 工作方式

SpecWeaver 由三个数据源 MCP 和三个工作流 Skill 组成：

| 组件 | 作用 |
| --- | --- |
| Tower MCP | 读取任务分类、正文、评论、子任务和附件；经确认后发布去重评论 |
| Eolink MCP | 验证登录状态并读取项目、接口列表和接口详情 |
| 蓝湖 MCP | 验证 Cookie、读取标准 stage 项目的设计列表并下载原图 |
| `configure-specweaver` | 补齐或按平台更新认证信息，并检查可直接验证的数据源 |
| `tower-requirement-collection` | 执行 Bug 快速分析或普通需求资料收集 |
| `git-commit` | 审查改动、验证并生成受控提交，按确认同步 Tower |

Skill 是 Agent 行为和流程约束的来源；MCP 只负责读取或执行明确的数据源操作。
完整资料收集生成的文件写入当前开发项目，不写入插件安装目录。

## Agent 上下文

仓库还包含以下面向大模型的说明：

- [`AGENTS.md`](./AGENTS.md)：适用于 Codex、Cursor 等通用 Agent；
- [`CLAUDE.md`](./CLAUDE.md)：Claude Code 的插件上下文和运行约束。
- [`rules/specweaver.mdc`](./rules/specweaver.mdc)：Cursor 原生的安装、更新、
  配置与故障处理规则。

这些文件用于帮助 Agent 正确理解插件边界，不能代替具体 Skill。命中 Skill
时，Agent 仍应完整读取对应 `SKILL.md` 并遵循其中流程。

## 安全边界

- 不在对话、生成文档、提交、PR 或日志中输出 Cookie、密码、Token 和登录响应；
- 不读取或展示 `~/.specweaver/.env` 的内容；
- 不把认证信息写入项目级 `.env` 或插件安装目录；
- 不在用户未确认时发布 Tower 评论；
- 不因单个数据源不可用而伪造资料；应说明影响范围并让用户选择重试或明确降级；
- 不直接修改公开插件仓库来修复问题；已发布版本通过更高版本替换。

## 故障排查

### 插件已经安装，但 Agent 找不到 Skill 或 MCP

先按当前平台重新加载插件：

- Codex：新建 Agent 任务；
- Claude Code：新建会话，必要时重启；
- Cursor：执行 `Developer: Reload Window` 后新建任务。

仍未识别时，先更新 marketplace，再重新安装插件。不要手动修改平台缓存中的
插件文件。

### 配置成功后仍提示认证失效

运行提示中的 `specweaver configure <platform>`，只更新失效的数据源。若使用了自定义
`SPECWEAVER_HOME`，必须在启动客户端前设置，确保客户端和配置向导读取同一目录。

### 找不到 `uv`

在终端执行 `uv --version`。若命令不存在，按
[`uv` 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)
安装后重启宿主客户端。

### 蓝湖能力暂时不需要

运行 `specweaver configure lanhu` 并选择关闭蓝湖。关闭后，需求流程不会询问、
读取或下载蓝湖资料；Tower 和 Eolink 能力不受影响。

## 插件目录

```text
SpecWeaver/
├── README.md
├── AGENTS.md
├── CLAUDE.md
├── install.sh
├── .agents/plugins/marketplace.json
├── .codex-plugin/plugin.json
├── .claude-plugin/
├── .cursor-plugin/
├── .mcp.json
├── .mcp.claude.json
├── .mcp.cursor.json
├── skills/
├── rules/
├── mcp/
├── scripts/
└── release-notes/
```

## 版本与支持

版本说明见 [`release-notes/`](./release-notes/)。安装问题请在公开仓库提交
Issue，并提供平台、插件版本、可公开的错误信息和复现步骤。不要附带 Cookie、
密码、Token、私有任务内容或完整登录响应。
