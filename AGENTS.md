# SpecWeaver Agent 指南

## 你正在处理什么

当前目录是 SpecWeaver 插件根目录，不是普通业务项目。SpecWeaver 把 Tower、
蓝湖和 Eolink 中分散的需求上下文整理为可追溯资料，并提供受控的 Git 提交流程。

插件支持 Codex、Claude Code 和 Cursor。平台清单、Skill、MCP 与运行脚本均以
当前目录为根；不要假设它们位于外层开发仓库中。

本文件是 Codex 在 SpecWeaver 仓库目录中工作时读取的仓库级说明。插件安装后的
运行流程仍以各 Skill 的 `SKILL.md` 为准；不要把本文件复制到用户业务项目。

## 组件职责

- `skills/configure-specweaver/`：配置认证和验证数据源连接；
- `skills/tower-requirement-collection/`：读取 Tower，并执行 Bug 快速分析或
  普通需求资料收集；
- `skills/git-commit/`：审查、验证和提交明确范围的 Git 改动；
- `mcp/tower/`：Tower 任务读取和经确认的评论发布；
- `mcp/eolink/`：Eolink 项目与 API 读取；
- `mcp/lanhu/`：蓝湖认证、设计列表与原图读取；
- `scripts/`：MCP 启动、本地认证配置和 `specweaver` 终端命令。

Skill 定义工作流，MCP 提供数据能力。不要绕过 Skill 自行拼接流程，也不要把
MCP 返回结果当作已经确认的需求结论。

## Codex 首次安装与日常维护

当用户要求在 Codex 中安装 SpecWeaver 时，按“环境检查 → 添加 marketplace →
安装插件 → 终端配置 → 新任务加载 → 首次使用验证”的顺序处理。安装与配置应在
同一个终端流程中完成，不能把插件已经下载描述成数据源已经可用。

### 1. 安装前检查

先确认 Git、Codex 和 `uv` 可用：

```bash
git --version
codex --version
uv --version
```

插件支持 macOS 和 Linux；Windows 建议在 WSL 中使用。安装源是公开 GitHub 仓库，
统一安装器会自行管理 `~/.specweaver/runtime`，不需要访问 SpecWeaver 的开发仓库。

若 `uv` 不存在，先引导用户按官方方式安装并重新打开终端。不要通过修改插件缓存、
伪造可执行文件或跳过 MCP 依赖来绕过检查。

### 2. 首次安装并配置

Codex 用户推荐在普通终端执行一条命令：

```bash
curl -fsSL https://raw.githubusercontent.com/yangfanfengshun/SpecWeaver/master/install.sh | bash -s -- --codex
```

该命令安装或复用 Codex 中的 `specweaver@specweaver`，将公共终端入口指向
`~/.specweaver/runtime`，并立即补齐缺失配置。Cookie 和密码通过终端隐藏输入，
不能发送到 Codex 对话。配置保存在 `~/.specweaver/.env`。

用户明确要求同时安装本机已存在的多个 AI 宿主时，省略 `--codex`：

```bash
curl -fsSL https://raw.githubusercontent.com/yangfanfengshun/SpecWeaver/master/install.sh | bash
```

现有手动安装方式继续作为单平台安装和故障恢复入口，下面的代码块可以整段复制：

```bash
codex plugin marketplace add yangfanfengshun/SpecWeaver && \
codex plugin add specweaver@specweaver && \
~/.codex/plugins/cache/specweaver/specweaver/0.5.0/scripts/setup.sh --configure
```

`specweaver@specweaver` 的前半部分是插件 ID，后半部分是 marketplace 名称。
`setup.sh --configure` 会安装 `specweaver` 终端入口并立即补齐缺失配置。插件升级
时使用新版本号对应的缓存路径。

上述缓存路径已在 macOS 验证；Windows 路径尚未验证。Windows 用户可以按实际缓存
位置调整命令，或者回到 Codex App 发送“配置 SpecWeaver”，由 AI 定位插件并启动
配置。

首次配置只询问缺失项。蓝湖只收集是否启用和 Cookie，不要求项目链接；没有真实
项目链接时标记为“已配置，待首次使用验证”，第一次读取真实设计稿时再验证 Cookie
和项目权限。

若当前 Codex 客户端提供插件目录或专用插件管理工具，优先使用该界面或工具完成
同一安装动作；不要为了绕过宿主权限策略而强制改用终端。

### 3. 加载插件

首次安装和配置完成后，新建一个 Codex Agent 任务。插件 Skills 和 MCP 工具以新任务
为安全加载边界；不要在旧任务中仅凭安装命令成功就声称新版本已经生效。

如果宿主明确要求重启或重新加载，先完成对应操作，再创建新任务。

### 4. 验证安装

先确认 marketplace 中能看到插件：

```bash
codex plugin list --marketplace specweaver
```

再让用户提供一个自己有权访问的 Tower 任务链接，并按正常需求收集流程读取。能够
触发 `tower-requirement-collection`、调用 Tower MCP 并返回真实任务信息，才说明
插件、Skill、MCP 和认证链路均已正常工作。

### 更新已有安装

首次安装闭环完成后，只有用户明确要求升级或排查版本时才进入本节。先刷新
runtime、marketplace 和插件：

```bash
specweaver update --codex
specweaver status
```

`specweaver update` 不覆盖 `~/.specweaver/.env`，runtime 存在本地修改时停止，
不会强行覆盖。更新完成后新建 Codex Agent 任务。

没有使用统一安装入口时，继续使用原生命令：

```bash
codex plugin marketplace upgrade specweaver
codex plugin add specweaver@specweaver
```

插件使用显式 SemVer。不要直接修改 `~/.codex/plugins/cache` 中的 `plugin.json`
或复制文件覆盖缓存来制造更新结果。更新后使用新版本缓存中的
`scripts/setup.sh --configure`，让终端入口指向新版本，然后新建 Codex Agent
任务。

### 日后更新认证或检查连接

```bash
specweaver configure tower
specweaver configure eolink
specweaver configure lanhu
specweaver check
```

不带平台名的 `specweaver configure` 只补齐缺失项；带平台名时只询问并验证该平台。
Tower、Eolink 或蓝湖单独失效时，不得让用户重填其他平台。

### 安装故障处理

- marketplace 找不到：执行
  `codex plugin marketplace upgrade specweaver` 后重试；
- 插件已安装但 Skill 或 MCP 未出现：新建 Agent 任务，必要时重启宿主；
- MCP 启动失败：确认 `uv --version` 正常，并检查宿主提供的 MCP 状态与错误信息；
- 认证失败：不要重复安装插件，运行对应的
  `specweaver configure <platform>`；
- 更新后仍是旧版本：核对 `codex plugin list --marketplace specweaver`，重新刷新
  marketplace 并安装，不直接编辑插件缓存。

执行安装或更新前，应向用户说明会修改其 Codex marketplace 和插件配置；命令失败
时报告实际错误，不得把 marketplace 已添加、插件已下载或宿主待重载说成安装完成。

## 处理用户请求

### 配置与认证

用户要求安装后初始化、配置、重新配置、更新 Cookie 或密码、检查连接时，使用
`configure-specweaver` Skill。

- 认证信息只通过终端隐藏输入；
- 不要求用户在对话中粘贴 Cookie、密码或 Token；
- 不读取、展示或总结 `~/.specweaver/.env`；
- 配置失败时区分未配置、能力关闭、已配置待首次使用验证、登录失效、无权限和
  网络错误；
- 只更新失败平台，不重新收集其他平台的凭据；
- 不把 Tower 任务链接或蓝湖项目链接作为安装配置的必填项。

### Tower 任务

用户提供 Tower 任务链接或要求分析 Bug、整理需求、补齐设计/API 上下文时，使用
`tower-requirement-collection` Skill。

- 分类为 `BUG管理` 时直接进行快速分析，在对话中输出，不创建资料文件；
- 普通需求先展示 Tower、蓝湖和 Eolink 的已发现状态，再让用户选择快速分析或
  完整资料收集；
- 完整模式必须先确认设计稿与 API 范围，再下载和生成文件；
- 只记录可追溯事实，不虚构缺失的设计、接口或验收条件；
- 数据源认证失败时暂停依赖步骤，让用户重配或明确选择降级。

### Git 提交

用户明确要求提交、生成提交信息、按 Tower 需求提交或同步提交信息到 Tower 时，
使用 `git-commit` Skill。

- 只处理用户明确授权范围内的改动；
- 提交前完成必要验证；
- 使用 Conventional Commits；
- Tower 评论先预览，用户确认后才发布；
- 不自动推送、创建 PR、合并或发布版本。

## 文件与输出边界

- 需求资料写入用户当前项目约定的位置，不写入插件安装目录；
- 不修改用户代码，除非用户明确要求进入开发实施；
- 不把快速分析升级成完整资料收集；
- 不在缺少确认时下载多组设计稿或 API；
- 不把私有链接、认证信息和登录响应写入公开文档、提交或日志；
- 不编辑平台缓存中的插件副本来“永久修复”问题。

## 读取顺序

1. 根据用户意图选择匹配的 Skill；
2. 完整读取该 Skill 的 `SKILL.md`；
3. 只按 Skill 指向读取必要引用资料；
4. 调用对应 MCP；
5. 明确区分数据源事实、推断和用户决策；
6. 按 Skill 的完成条件验证输出。

如果没有 Skill 覆盖请求，说明插件不提供该流程，再使用宿主 Agent 的常规能力。
不要假装 SpecWeaver 已经执行了不具备的操作。

## 安全规则

- 绝不输出 Cookie、密码、Token、`.env` 内容或完整登录响应；
- 绝不把认证信息提交到 Git；
- 绝不在未确认时向 Tower 写评论；
- 绝不伪造 Tower、蓝湖或 Eolink 返回内容；
- 绝不覆盖、删除或强推已发布 tag；
- 外部写操作失败时说明实际状态，不声称成功。

## 修改插件本身时

若用户明确要求开发或修复 SpecWeaver：

- 保持三平台的版本和核心描述一致；
- 保持清单路径相对于插件根目录；
- 只改与请求直接相关的文件；
- 运行外层开发仓库提供的测试和发布检查；
- 公开发布必须使用更高的 SemVer 和对应版本说明。

公开仓库可能是自动生成的发布快照。若当前目录来自公开仓库，应回到其开发仓库
修改来源文件，不要直接维护生成结果。
