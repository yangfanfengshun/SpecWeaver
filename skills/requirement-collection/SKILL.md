---
name: requirement-collection
description: 编排 Tower、蓝湖、Eolink 等来源的需求资料收集，执行快速分析或完整资料收集，并生成 requirement.md、api.md、design-context.json 和本地证据。用户提供 Tower 任务链接、要求分析 Bug、梳理需求、补齐设计/API 上下文、确认多组资料范围或生成 docs/tower/ 资料时使用。只收集可追溯事实，不制定开发计划、不分析代码改动、不执行开发。
---

# 需求资料收集

## 边界

- 把一次需求请求作为一个独立任务处理。
- 只使用来源 Skill 返回的事实和用户明确补充的信息；标出来源，不按经验补全。
- 总控负责模式、范围、文件命名、文档生成和最终验证；来源 Skill 不写最终文档。
- BUG 或快速模式只在对话中回答；完整模式才创建资料目录。
- 不发布外部评论，不分析代码范围，不制定技术方案、开发计划或工期。
- 完成当前路线后立即停止，不进入开发。

完整模式生成文件前读取：

- [来源结果协议](references/source-result-contract.md)
- [需求文档模板](references/requirement-template.md)
- [API 文档模板](references/api-template.md)
- [设计上下文模板](assets/design-context.template.json)

快速模式不要加载模板。

## 来源路由

根据已发现来源读取对应 Skill 的完整 `SKILL.md`，再按其规则收集：

| 来源 | 来源 Skill | 主要职责 |
| --- | --- | --- |
| Tower | `tower-source-collection` | 任务分类、正文、评论、子任务、附件和图文位置 |
| 蓝湖 | `lanhu-source-collection` | 设计候选、预览图、规范化结构和切图 |
| Eolink | `eolink-source-collection` | 项目、分组、接口、字段和示例 |

新增平台时使用新的 `<platform>-source-collection` Skill，并遵守来源结果协议。总控
只能依赖协议字段，不复制平台 API、认证或下载细节。

## 状态机

严格按以下状态转换，不满足门槛时暂停：

```text
PRIMARY_SOURCE_READ
→ TYPE_DECIDED
→ MODE_SELECTED
→ MATERIAL_SCOPE_CONFIRMED        # 仅完整模式
→ SOURCES_COLLECTED               # 仅完整模式
→ DOCUMENTS_WRITTEN               # 仅完整模式
→ VERIFIED                        # 仅完整模式
→ DONE
```

始终保留已读取事实和用户选择。认证更新或用户回答后从当前失败状态继续，不重复已完成
的来源读取。

## 1. 读取主来源并决定模式

Tower 链接作为主来源时，使用 `tower-source-collection` 读取任务，但先不下载附件。

- 任一 Tower 分类名称与 `BUG管理` 完全一致：自动进入快速模式，读取包含附件的完整
  Tower 结果，输出 Bug 摘要、触发条件、当前表现、期望表现、影响范围、证据和未明确
  事项；不读取其他来源、不创建文件，随后进入 `DONE`。
- 普通需求：展示已发现的设计、API 和其他来源状态，让用户选择“快速分析”或
  “完整资料收集”。存在外部资料、多页面或复杂规则时推荐完整模式，但不替用户选择。
- 快速模式：只读取主来源及其附件，在对话中回答；不读取蓝湖或 Eolink，不创建目录。

需要选择时优先使用宿主原生选择工具；不可用时使用编号文字。提问后暂停，收到回答前
不得继续。

## 2. 确认完整模式资料范围

先检查目标目录中是否已有同一需求的 `requirement.md`；其中已记录资料状态、采用范围
和依据，且主来源没有出现改变范围的新信息时，复用选择。

对每个已发现来源：

1. 先调用来源 Skill 的“列举/检查”能力，不下载完整产物。
2. 只有唯一且与需求明确关联的候选时直接采用。
3. 缺失、存在多组或关联不明时，只询问实际缺失或不明确项。
4. 允许用户补充、跳过、取消或改变选择；记录采用与未采用范围及依据。
5. 范围确认前不得下载附件、设计详情、预览图、切图或生成文档。

`disabled` 表示本机未启用能力，不等于资料不存在；`auth_expired`、`forbidden`、
`network_error` 和 `not_found` 必须保持各自状态，不得静默降级。

## 3. 收集已确认来源

创建 `docs/tower/<Tower原始标题>/design/` 和
`docs/tower/<Tower原始标题>/images/`；只替换操作系统禁止的目录字符。

1. 依次调用已确认来源 Skill，传入明确范围和绝对输出目录。
2. 要求每个来源按来源结果协议返回结果；不把完整大对象复制到对话。
3. 逐张查看成功保存的 Tower 附件和设计预览图。
4. 保留来源 URL、稳定编号、本地文件、失败原因、用户选择和未解决事项。
5. 相同二进制内容只保留一个文件，但每次原始出现位置和来源映射都必须保留。
6. 任何来源失败只暂停依赖它的步骤；提示重新配置对应平台或由用户明确选择跳过。

## 4. 生成完整资料

固定结构：

```text
docs/tower/<Tower任务名称>/
├── requirement.md
├── api.md
├── design-context.json
├── design/
│   └── lanhu-001.json
└── images/
    ├── tower-001.png
    ├── lanhu-001-preview.png
    └── lanhu-slices/
        └── lanhu-001/{icon,img,bg}/
```

- 总控独占 `requirement.md`、`api.md` 和 `design-context.json` 的写入权。
- 按模板生成两份 Markdown，删除占位说明和未使用行。
- Tower 原始图文必须保持正文和评论的原始顺序；成功图片替换为本地相对路径，失败
  图片在原位置记录原因和来源链接。
- `requirement.md` 只写设计结论、预览和证据链接，不嵌入完整图层树或资产清单。
- API 不涉及、等待后端或无资料时仍生成 `api.md`，只写状态与依据。
- 按模板生成小型 `design-context.json`，将需求标识映射到设计名称、ID、来源 URL、
  预览图、结构文件、画布和切图目录；不得嵌入图层树。
- 同一需求重复运行时更新同一目录，只更新工具管理的文档和对应来源文件，不删除人工
  文件。

## 5. 完成前验证

- 主来源内容、全部评论/附件线索、资料状态、采用范围和用户选择已处理。
- 所有来源结果符合协议且不含 Cookie、密码、Token、Authorization 或登录响应。
- 两份 Markdown、`design-context.json` 及所有声明成功的文件真实存在。
- 文档链接、图片相对路径和设计上下文中的相对路径都能解析到真实文件。
- Tower 图文出现顺序未改变；每次出现都能对应本地文件或明确失败占位。
- 每张设计的预览图、结构文件、设计 ID、画布和切图映射互相一致。
- 设计事实与 `source: derived` 的推导结果没有混淆。
- 文档未混入实现建议、开发计划、代码分析或插件内部规则。

任一检查失败时修复或明确报告阻塞；没有验证证据时不得声明完成。全部通过后进入
`DONE`。
