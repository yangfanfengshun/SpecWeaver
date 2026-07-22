# SpecWeaver

需求编织器，把 Tower、蓝湖和 Eolink 中分散的上下文编织成可追溯、可执行的需求资料。

> Weave scattered context into actionable specs.

仓库根目录就是 SpecWeaver 插件本体。平台安装后直接从自身缓存运行，不会再次从 GitHub 下载一份 MCP 源码。

## 能力

- 读取 Tower 分类、正文、全部评论、子任务与附件；
- `BUG管理` 自动快速分析，普通需求可选择快速分析或完整资料收集；
- 完整模式按需读取蓝湖设计稿和 Eolink API，生成 `requirement.md`、`api.md` 与本地图片证据；
- 蓝湖 MCP 只使用 HTTP，不依赖上游 MCP、Playwright 或 Chromium；
- 认证失效时区分未配置、能力关闭、登录失效、无权限和网络错误，并允许更新后从失败节点重试；
- 通过 Git 提交 Skill 生成受控的 Conventional Commit，并在用户确认后向关联 Tower 写入去重评论。

## 运行要求

- macOS 或 Linux；Windows 建议使用 WSL；
- Python 3.10～3.13；
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)；
- Codex、Claude Code 或 Cursor 之一；
- 可访问 Tower、Eolink，以及启用设计能力时的蓝湖。

MCP 依赖由 `uv` 根据入口脚本声明准备，插件目录不维护 `.venv`。

## 安装与首次配置

首次使用需要依次完成“安装插件、加载插件、配置认证、验证连接”四个步骤。只执行安装命令不会弹出 Cookie 输入框，也不能直接读取 Tower、Eolink 或蓝湖。

### 1. 安装前准备

- 确认本机满足上面的运行要求，并且终端可以执行 `uv --version`；
- 确认可以访问 GitHub；插件从公开发布仓库安装，不需要私有开发仓库权限；
- 在浏览器中登录需要使用的 Tower 和蓝湖账号；
- 准备 Eolink 根地址、登录账号和密码。

Tower 和蓝湖的 Cookie 获取方式：

1. 打开浏览器开发者工具的 Network 面板；
2. 刷新 Tower 或蓝湖页面；
3. 选择一个发往对应域名的请求；
4. 从 Request Headers 中复制完整的 Cookie；
5. Cookie 只粘贴到后续的终端配置向导，不要发送到 Agent 对话中。

### 2. 安装插件

三个平台都直接从 GitHub 安装，用户无需执行 `git clone`。选择自己使用的平台完成安装即可。

#### Codex

```bash
codex plugin marketplace add yangfanfengshun/SpecWeaver \
  --ref v0.4.2
codex plugin add specweaver --marketplace specweaver
```

#### Claude Code

```bash
claude plugin marketplace add yangfanfengshun/SpecWeaver@v0.4.2
claude plugin install specweaver
```

#### Cursor

在 Cursor Agent 中运行：

```text
/add-plugin https://github.com/yangfanfengshun/SpecWeaver
```

然后从导入的 marketplace 中安装 `specweaver`，并在插件详情确认版本为 `0.4.2`。

发布版本应使用对应 tag 或固定 ref，避免安装内容随开发分支漂移。完成这一步只代表插件已安装，认证信息尚未配置。

### 3. 加载插件并启动配置向导

安装完成后，让客户端重新加载插件：

- Codex：新建一个 Agent 任务；
- Claude Code：新建会话；如果仍未识别插件，重启 Claude Code；
- Cursor：执行 `Developer: Reload Window`，然后新建一个 Agent 任务。

在新任务或新会话中直接说：

```text
配置 SpecWeaver
```

`configure-specweaver` Skill 会从平台缓存中定位插件，并在终端运行交互式配置向导。如果客户端询问是否允许执行终端命令，需要确认允许。

### 4. 填写认证信息

按照终端提示依次填写：

1. Tower Cookie；
2. Eolink 根地址、账号和密码；
3. 是否启用蓝湖设计稿能力；
4. 启用蓝湖时，填写蓝湖 Cookie 和一个有权访问的标准 stage 项目链接。项目链接只用于验证，不会保存。

Cookie 和密码采用隐藏输入，不会显示在终端中。向导会立即联网验证 Tower、Eolink 和蓝湖的认证状态；验证失败时，可以根据提示重新填写。

配置保存到：

```text
~/.specweaver/.env
```

配置文件使用原子替换写入并设置为 `600` 权限。不要把该文件加入 Git，也不要在 Agent 对话中粘贴 Cookie、密码或文件内容。

当终端显示所有已启用的数据源验证成功后，首次配置完成，可以开始使用 SpecWeaver。

### 5. 验证安装结果

在 Agent 任务中发送一个自己有权访问的 Tower 任务链接：

```text
整理这个 Tower 任务：https://tower.im/teams/<team-id>/todos/<todo-id>
```

插件能够读取任务并给出后续选项，说明安装、配置和 MCP 加载均已完成。

### 重新配置或更新认证

Cookie、密码失效或需要切换账号时，在新的 Agent 任务中再次说：

```text
配置 SpecWeaver
```

向导会保留已有值，用户可以只更新需要变化的认证信息。更新并验证成功后，从原流程的失败节点重试即可。

如果已经知道平台缓存中的插件目录，也可以直接在该目录执行：

```bash
./scripts/setup.sh --configure
```

如需更换配置目录，请在启动客户端前设置 `SPECWEAVER_HOME`。

### 自动化环境

自动化环境可预先设置下列变量后，在已安装插件目录运行 `./scripts/setup.sh --non-interactive`：

| 变量 | 必需条件 | 用途 |
| --- | --- | --- |
| `TOWER_COOKIE` | 始终 | 读取 Tower 与按确认发布评论 |
| `EOLINK_BASE_URL` | 始终 | Eolink 站点根地址 |
| `EOLINK_USER` | 始终 | Eolink 登录账号 |
| `EOLINK_PASSWORD` | 始终 | Eolink 登录密码 |
| `LANHU_ENABLED` | 始终 | 只接受 `true` 或 `false` |
| `LANHU_COOKIE` | 蓝湖启用时 | 读取设计稿与原图 |
| `LANHU_CHECK_URL` | 非交互且蓝湖启用时 | 用标准 stage 项目验证权限，不写入配置 |

旧配置缺少 `LANHU_ENABLED` 时按 `true` 处理。设置为 `false` 后，需求流程不会询问、读取或下载蓝湖资料。

## 使用

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

## 认证失效

当 Tower、Eolink 或蓝湖认证失效时，插件会暂停依赖该平台的步骤并提示受影响范围。重新说“配置 SpecWeaver”，更新认证并验证成功后，从失败节点重试即可，不需要重跑整个流程。

- Tower 失效：暂停整个流程；
- 蓝湖失效：更新后重试，或明确确认本次不采用设计稿；
- Eolink 失效：更新后重试，或明确确认本次不采用 API；
- 不输出 Cookie、密码或登录响应。

## 技术标识

- 插件 ID：`specweaver`
- 配置与数据目录：`~/.specweaver`
- 自定义目录变量：`SPECWEAVER_HOME`
- MCP：`specweaver-tower`、`specweaver-eolink`、`specweaver-lanhu`

