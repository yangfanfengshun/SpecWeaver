---
name: tower-source-collection
description: 从 Tower 读取任务分类、正文、全部评论、子任务、附件线索和原始图文位置，并按统一来源协议返回可追溯事实。用户直接提供 Tower 任务链接、总控需求收集流程需要读取 Tower，或需要单独核对 Tower 任务与附件证据时使用。不选择处理模式、不读取其他平台、不生成最终需求文档。
---

# Tower 来源采集

## 输入与边界

- 接收 Tower 任务 URL，以及可选的 `include_images` 和绝对 `output_dir`。
- 只负责 Tower 事实、附件和来源映射；不决定快速/完整模式，不调用蓝湖或 Eolink。
- 不生成 `requirement.md`、`api.md` 或 `design-context.json`，不发布 Tower 评论。
- 向总控返回结果时遵守
  [来源结果协议](../requirement-collection/references/source-result-contract.md)。

## 读取流程

1. 验证输入是 Tower 任务链接。
2. 调用 `tower_read_todo(url, include_images=false)`，读取分类、正文、全部评论、子任务、
   附件清单、外部链接和 `image_occurrences`。
3. 检查全部分类：只要任一分类名称与 `BUG管理` 完全一致，返回
   `task_type: bug`；分类为空或无法确认时返回 `task_type: requirement`，不得按标题猜。
4. 从正文和评论中提取蓝湖、Eolink、Tower 原型及其他外部来源线索，放入
   `discovered_sources`，不读取这些平台。
5. 只有调用方明确要求查看附件时，才以 `include_images=true` 重读；Markdown 图片
   标记必须继续留在正文或对应评论的原始位置。
6. 只有调用方传入已确认的绝对 `output_dir` 时，才调用 `tower_download_images`。
   保留每个 occurrence 与本地文件或失败占位的映射。

## 结果要求

- `items` 至少包含任务 ID、标题、状态、分类、正文、全部评论、父/子任务和
  `task_type`。
- `artifacts` 只记录真实保存的附件；相同内容可共用文件，但不能合并 occurrence。
- `provenance` 保留 Tower URL、正文/评论范围、原始图片 URL 和出现位置。
- `unresolved` 记录缺失字段、附件失败或来源关联不明，不用经验补齐。
- Tower 认证失效时返回 `auth_expired` 并提示 `specweaver configure tower`；区分
  `forbidden`、`network_error` 和 `not_found`，不盲目重试。
- 不输出 Cookie、邮箱、密码、登录响应或其他敏感信息。

独立使用时只返回 Tower 来源摘要和证据状态，不升级为完整资料收集。
