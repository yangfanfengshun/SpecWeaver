---
name: requirement-collection
description: 读取 Tower 任务并按用户意图执行快速分析或确定性完整收集。用户提供 Tower 链接、要求分析 Bug、快速梳理需求、收集 Tower/蓝湖/Eolink 来源或生成 docs/tower 来源资料时使用。完整收集只调用统一脚本写来源文件，结束后询问是否分析；不生成 requirement.md、不分析代码、不执行开发。
---

# 需求资料收集

## 边界

- 收集和分析是两个动作。
- Tower、附件、蓝湖和 Eolink 的格式、文件名、排序、写入与验证由 MCP 脚本负责。
- Agent 不组合来源 MCP、不改写来源文件、不自行选择歧义候选。
- Bug 和快速模式只在对话中回答，不在用户项目生成文件。
- 完整收集不生成 `requirement.md`；用户确认分析后改用 `requirement-analysis`。
- 不制定技术方案、代码范围、开发计划或工期，不开始开发。

## 1. Tower 预读

调用 `tower_read_todo(url, include_images=false)`。

该工具会把可读原文和机器元数据分别原子写入用户缓存：

```text
~/.specweaver/cache/tower/<任务ID>/
├── tower-raw.md
└── tower-metadata.json
```

工具结果只包含任务类型、缓存路径、评论/附件/子任务数量、外部来源和未解决事项。

- 不要求工具把全文返回对话。
- 需要分析 Tower 内容时，由 Agent 读取结果中的 `cache_file`。
- 子任务默认只保留标题和链接；用户明确要求时再单独读取指定子任务。
- 只有明确 `Bug` Tag 才是 `task_type: bug`，其他情况均为普通需求。

## 2. 选择路线

### Bug

`task_type: bug` 时自动进入快速路线：

1. 读取缓存中的 `tower-raw.md`。
2. 缓存表明关键事实位于图片时，把相关图片临时下载到系统临时目录；分析结束后删除。
   超大文件、视频或压缩包必须先征得用户同意。
3. 在对话中输出 Bug 现象、触发条件、期望、影响、证据和未明确事项。
4. 不读取蓝湖或 Eolink，不在项目写文件，不生成 `requirement.md`，随后停止。

### 普通需求

- 用户明确要求快速分析：进入快速路线。
- 用户明确要求完整收集：进入完整收集。
- 意图不明确：询问是否需要完整收集，收到回答前暂停。
- 用户回答“不需要完整收集”或同义表达：进入快速路线。

快速路线默认只读取缓存中的 `tower-raw.md` 并在对话中回答，不读取蓝湖或 Eolink，
不在项目写文件，不生成 `requirement.md`。缓存表明结论依赖图片时可临时下载相关
图片，分析结束后删除；超大文件、视频或压缩包先征得用户同意。

## 3. 完整收集

### 3.1 候选与范围

先调用：

```text
requirement_collect(tower_url)
```

脚本只读取 Tower 预读阶段生成的缓存并返回候选，不重复请求 Tower，
不写用户项目。缓存缺失时先返回 Tower 预读步骤。

- `status: scope_ready`：脚本已确定所有来源均为唯一明确候选，可使用返回的
  `suggested_scope`。
- `status: scope_confirmation_required`：只展示脚本返回的候选，让用户选择、跳过、
  补充或取消；Agent 不自行扩大或改变范围。
- 认证、权限、网络或来源失败保持原状态并暂停该来源。候选读取阶段失败时，用户重新
  配置后再次调用 `requirement_collect(tower_url)`；没有用户决定不得继续。明确跳过
  时从采用数组移除，并在 `skipped_sources` 记录来源、URL 和原因。

同时确认绝对项目输出目录。默认使用脚本返回的 `suggested_directory_name` 放到
`<项目>/docs/tower/` 下，不由 Agent 自行清洗 Tower 标题。

### 3.2 一次性写入

范围和目录确定后只调用一次：

```text
requirement_collect(tower_url, output_dir, confirmed_scope)
```

`confirmed_scope` 必须显式包含：

```json
{
  "tower_attachments": true,
  "allow_restricted_attachments": false,
  "replace_existing": false,
  "lanhu": [],
  "eolink": [],
  "skipped_sources": []
}
```

蓝湖项使用脚本返回的 `url`、`image_id` 和名称；Eolink 项使用 `url` 与用户确认的
`api_ids`。省略 `api_ids` 只用于用户明确采用该链接下全部接口的情况。

视频、压缩包或已知超大附件只有用户确认后才把
`allow_restricted_attachments` 设为 `true`。

目标目录已有 `tower-raw.md` 或脚本管理的来源目录时，
工具返回 `existing_output_confirmation_required`，不得静默覆盖。用户明确确认更新
同一目录后把 `replace_existing` 设为 `true`；用户选择新目录时保持 `false`。脚本只
更新自己管理的来源路径，不删除人工文件。

完整写入返回 `partial` 时先展示 `unresolved` 并暂停：

- 用户选择重试：保留原 `output_dir` 和已确认范围，把 `replace_existing` 设为
  `true` 后重新调用统一入口；当前版本会确定性重跑所选来源，不承诺只请求失败来源。
- 用户选择跳过蓝湖或 Eolink：从相应采用数组移除，写入 `skipped_sources`，把
  `replace_existing` 设为 `true` 后重新调用统一入口。
- 用户只跳过某个 Tower 附件：保持 `tower_attachments: true`，在
  `skipped_sources` 记录 `source: tower`、该附件来源 URL 和原因；脚本只跳过该 URL。
  用户跳过全部 Tower 附件时把 `tower_attachments` 设为 `false`。
- 用户明确接受现有缺失并要求分析：可转入分析，但必须保留 `partial` 状态及影响。

脚本直接在项目写入并验证：

```text
<output_dir>/
├── tower-raw.md
├── tower-attachments/
├── api/
└── images/
    ├── <设计名称>--<image_id>-preview.<ext>
    └── lanhu-slices/<设计名称>--<image_id>/
```

机器清单写入
`~/.specweaver/cache/requirements/<Tower-ID>/<输出目录哈希>/manifest.json`；Tower 附件
映射直接包含在该清单中，不单独生成 `tower-attachments.json`。蓝湖规范化结构写入
独立缓存
`~/.specweaver/cache/lanhu/<image_id>/<设计名称>--<image_id>.json`。用户缓存只放
轻量 Markdown/JSON，图片、切图和附件仍留在项目目录。

Eolink 每个接口独立保存为 `api/<API-ID>-<接口名称>.json`，按 API ID 排序。

不要调用 `tower_download_images`、`lanhu_get_design_detail`、
`lanhu_download_design_images`、`lanhu_download_slices` 或 `eolink_read_url` 自行重组
完整收集。

## 4. 收集结束

根据统一工具的小型结果报告：

- 输出目录；
- Tower、附件、蓝湖设计和 Eolink API 数量；
- 验证状态、失败和待确认项。

随后询问用户是否现在分析需求：

- 否或稍后：保留来源文件并停止。
- 是：完整读取 `../requirement-analysis/SKILL.md`，从已收集目录继续。

用户未确认分析前，不得创建或更新 `requirement.md`。
