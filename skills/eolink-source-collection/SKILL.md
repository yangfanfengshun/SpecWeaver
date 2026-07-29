---
name: eolink-source-collection
description: 从 Eolink 链接或 API ID 读取项目、分组、接口、请求参数、响应字段、枚举和示例，并按统一来源协议返回可追溯 API 事实。用户提供 Eolink 资料、要求单独核对接口定义，或总控需求收集流程需要 API 证据时使用。不推断未提供契约、不读取其他平台、不生成最终 API 文档。
---

# Eolink 来源采集

## 输入与边界

- 接收 Eolink URL、API ID 或总控已确认的接口范围。
- 只负责 API 来源事实；不决定需求模式，不生成 `api.md` 或其他最终文档。
- 向总控返回结果时遵守
  [来源结果协议](../requirement-collection/references/source-result-contract.md)。

## 收集流程

1. 有 Eolink 链接时调用 `eolink_read_url`；只有 API ID 时调用
   `eolink_get_interface_by_id`。
2. 项目或分组包含多组接口且关联不明时，返回候选清单，不自行扩大采用范围。
3. 范围确认后读取接口方法、路径、Content-Type、请求参数、响应字段、类型、单位、
   枚举、必填条件、示例、错误与备注。
4. 大型返回结果保存后提取接口/字段摘要，不在对话中打印或截断完整响应。
5. 相同 API ID 只保留一个条目，但保留它在不同来源中的每次引用。

## 结果要求

- `items` 每项至少包含 API ID、名称、方法、路径和文档状态。
- 字段事实保留方向、字段路径、类型、单位/枚举、必填条件、示例、说明和来源。
- `artifacts` 只记录调用方明确要求保存且真实存在的来源文件。
- `unresolved` 明确记录等待后端、资料缺失、冲突或字段歧义，不生成空接口。
- 认证失效时返回 `auth_expired` 并提示 `specweaver configure eolink`；区分
  `forbidden`、`network_error` 和 `not_found`，不得自动改成无 API。
- 不输出 Cookie、Token、Authorization 或登录响应。

独立使用时只返回 API 事实摘要，不分析调用代码或制定接入方案。
