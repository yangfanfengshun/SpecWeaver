# SpecWeaver for Claude Code

当前目录是 SpecWeaver 插件根目录。请把这里的 Skills 和 MCP 当作一个整体使用，
不要从 GitHub 另行下载运行副本。

## 插件目标

SpecWeaver 负责：

1. 从 Tower 读取任务分类、正文、评论、子任务和附件；
2. 对 `BUG管理` 任务进行快速分析；
3. 对普通需求按用户选择执行快速分析或完整资料收集；
4. 在完整模式下结合蓝湖规范化图层树、预览图、切图和 Eolink API，生成可追溯资料；
5. 在用户明确触发时记录当前项目的完成事项，并汇总当天跨项目日报；
6. 在用户要求时执行受控 Git 提交，并在确认后向 Tower 发布去重评论。

## 安装、更新与加载

当用户要求在 Claude Code 中安装 SpecWeaver 时，按“环境检查 → 添加 marketplace
→ 安装插件 → 提示独立配置命令 → 加载插件 → 首次使用验证”的顺序处理。不能把“命令执行成功”
描述成“已经可以读取数据源”。

### 1. 安装前检查

先确认 Git、Claude Code 和 `uv` 可用：

```bash
git --version
claude --version
uv --version
```

插件支持 macOS 和 Linux；Windows 建议在 WSL 中使用。安装源是公开 GitHub 仓库，
统一安装器会自行管理 `~/.specweaver/runtime`，不需要访问 SpecWeaver 的开发仓库。

若 `uv` 不存在，先引导用户按官方方式安装并重新打开终端。不要通过修改插件缓存、
伪造可执行文件或跳过 MCP 依赖来绕过检查。

### 2. 首次安装

Claude Code 用户推荐在普通终端执行一条命令：

```bash
curl -fsSL https://raw.githubusercontent.com/yangfanfengshun/SpecWeaver/master/install.sh | bash -s -- --claude
```

该命令安装或复用 Claude Code 中的 `specweaver@specweaver`，将公共终端入口指向
`~/.specweaver/runtime`，不会自动进入认证配置。用户明确要求同时处理三个宿主时，
省略 `--claude`；缺少某个宿主 CLI 只跳过该宿主。

现有手动安装方式继续作为单平台安装和故障恢复入口，下面的代码块可以整段复制：

```bash
claude plugin marketplace add yangfanfengshun/SpecWeaver && \
claude plugin install specweaver@specweaver && \
~/.claude/plugins/cache/specweaver/specweaver/0.7.3/scripts/setup.sh --install-cli
```

`specweaver@specweaver` 的前半部分是插件 ID，后半部分是 marketplace 名称。默认
安装到 user scope；只有用户明确要求团队共享或仅当前项目使用时，才选择
`project` 或 `local` scope。

第三条命令只安装后续使用的 `specweaver` 终端命令。随后另行运行
`specweaver configure`，从平台多选菜单进入配置。Tower 和蓝湖账号密码会立即验证
并生成 Cookie；Eolink 只保存、后验证。认证信息只能输入终端，密码不回显，不能
发送到 Claude 对话。配置保存在 `~/.specweaver/.env`。

上述缓存路径已在 macOS 验证；Windows 路径尚未验证。Windows 用户可以按实际缓存
位置调整命令，或者回到 Claude Code 对话发送“配置 SpecWeaver”，由 AI 定位插件
并启动配置。

### 3. 加载插件

在 Claude Code 交互会话中执行：

```text
/reload-plugins
```

重载成功后，应能看到加载的插件、Skills 和 MCP server 数量。若当前 Claude Code
版本不支持 `/reload-plugins`，新建会话；仍未加载时再重启 Claude Code。

安装或更新发生在当前会话中时，在重载完成前不要声称新版本已经生效。

### 4. 验证安装

先确认 Claude Code 能看到插件：

```bash
claude plugin list
```

再让用户提供一个自己有权访问的 Tower 任务链接，并按正常需求收集流程读取。能够
触发 `requirement-collection`、调用 Tower 来源 Skill 和 Tower MCP，并返回真实任务信息，才说明
插件、Skill、MCP 和认证链路均已正常工作。

### 更新已有安装

首次安装闭环完成后，只有用户明确要求升级或排查版本时才进入本节。先刷新
runtime、marketplace 和插件：

```bash
specweaver update --claude
specweaver status
```

`specweaver update` 不覆盖 `~/.specweaver/.env`，runtime 存在本地修改时停止，
不会强行覆盖。更新后执行 `/reload-plugins`；若当前版本不支持，再新建会话或重启。

没有使用统一安装入口时，继续使用原生命令：

```bash
claude plugin marketplace update specweaver
claude plugin update specweaver@specweaver
~/.claude/plugins/cache/specweaver/specweaver/0.7.3/scripts/setup.sh --install-cli
```

插件使用显式 SemVer。若 marketplace 已刷新但版本号没有提升，Claude Code 可能
判断当前缓存已经是最新版本；不要直接编辑缓存中的 `plugin.json` 来强制更新。
第三条命令会让终端入口指向当前插件版本；执行后重新加载插件。

Claude 插件通过 `.claude-plugin/plugin.json` 的 `mcpServers` 声明加载三个 MCP，
不需要手工编辑 `settings.json`。安装或更新后执行 `/reload-plugins`，再用 `/mcp`
检查 MCP 状态。

### 日后更新认证或检查连接

```bash
specweaver configure tower
specweaver configure eolink
specweaver configure lanhu
specweaver check
```

只处理用户指定或实际失效的平台，不得要求用户重填其他平台。

### 安装故障处理

- marketplace 找不到：执行
  `claude plugin marketplace update specweaver` 后重试安装；
- 插件已安装但组件未出现：执行 `/reload-plugins`，并查看 `/plugin` 的 Errors；
- MCP 启动失败：确认 `uv --version` 正常，再通过 `claude --debug` 查看启动错误；
- 认证失败：不要重复安装插件，运行对应的
  `specweaver configure <platform>`；
- 更新后仍是旧版本：核对 `claude plugin list` 返回的版本和 marketplace，再执行
  更新与重载，不直接修改 `~/.claude/plugins/cache`。

执行安装或更新命令前，应向用户说明会修改其 Claude Code 插件配置；命令失败时
报告实际错误，不得把 marketplace 已添加、插件已下载或重载已排队说成安装完成。

## Claude Code 入口

Claude Code 从以下文件发现插件：

- `.claude-plugin/marketplace.json`
- `.claude-plugin/plugin.json`
- `.mcp.claude.json`
- `skills/*/SKILL.md`

`.mcp.claude.json` 使用 `${CLAUDE_PLUGIN_ROOT}` 启动
`scripts/run-mcp.sh`。不要把该变量替换为开发机绝对路径，也不要假设当前工作目录
就是用户的业务项目。

## 必须遵循的流程

- 配置、更新认证或检查连接：使用 `configure-specweaver`；
- Tower Bug 或需求资料收集：使用 `requirement-collection`，再按来源调用
  `tower-source-collection`、`lanhu-source-collection` 和
  `eolink-source-collection`；
- 按已收集蓝湖设计开发页面：使用 `lanhu-design-implementation`；
- 记录本次完成事项或汇总当天跨项目日报：使用 `daily-report`；
- 审查并提交 Git 改动：使用 `git-commit`。

命中 Skill 后，先完整读取对应 `SKILL.md`。Skill 的步骤、暂停点、用户确认和完成
标准高于本文件中的概述。

普通需求不能直接静默进入完整模式。先展示已发现的设计稿与 API 状态，让用户选择
快速分析或完整资料收集；完整模式还要确认采用的资料范围。

`BUG管理` 任务默认只在对话中输出分析，不创建 `requirement.md`、`api.md` 或图片
目录。旧 `tower-requirement-collection` 只作为显式兼容入口，不维护第二套流程。

日报只在用户明确说“整理一下日报”或“整理今天日报”等指令后处理。记录模式只保存
项目名称和有完成证据的事项到 `~/.specweaver/daily-logs/YYYY-MM-DD.md`；汇总模式
读取当天对应文件并在对话中合并输出。不要补写进行中事项、问题或明日计划，也不要
声称未主动记录的任务已经进入日报。

## 认证和隐私

- 只让用户在终端填写 Cookie、账号和密码，密码输入不回显；
- 不让用户把凭证粘贴到 Claude 对话；
- 不读取或输出 `~/.specweaver/.env`；
- 不把认证信息写入用户项目、插件目录、提交或日志；
- 认证失效时只更新失败平台，再从失败节点继续；
- 不把 Tower 任务链接或蓝湖项目链接作为安装配置的必填项。

蓝湖能力可以通过 `LANHU_ENABLED=false` 关闭。关闭后不询问、不读取也不下载蓝湖
资料，不应把它误报为认证失败。

## 外部写操作

读取数据不等于授权写入。Tower 评论必须先 dry-run 展示，只有用户明确确认后才能
发布。Git Skill 不自动推送、创建 PR、合并或发布版本。

任何写操作失败时，报告实际结果和可重试节点；不得把预览、排队或部分成功描述成
已经完成。

## 输出要求

- 保留来源链接和资料之间的对应关系；
- 明确区分数据源事实、合理推断和仍需确认的问题；
- 缺少资料时说明缺口，不补写虚构内容；
- 需求资料写入用户当前项目，不写进 `${CLAUDE_PLUGIN_ROOT}`；
- 快速分析不产生文件，除非用户另有明确要求。

更完整的跨平台规则见 `AGENTS.md`，面向用户的安装与故障排查见 `README.md`。
