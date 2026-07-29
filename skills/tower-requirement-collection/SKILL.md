---
name: tower-requirement-collection
description: 兼容旧版 SpecWeaver 的 Tower 需求收集 Skill 名称。仅当用户明确点名 tower-requirement-collection、旧提示要求使用该名称，或需要延续旧任务状态时使用；新的 Tower Bug 分析和普通需求资料收集由 requirement-collection 编排，Tower 平台读取由 tower-source-collection 执行。
---

# Tower 需求资料收集兼容入口

1. 完整读取 `../requirement-collection/SKILL.md`，将它作为唯一总控规则。
2. Tower 平台读取完整遵循 `../tower-source-collection/SKILL.md`。
3. 保留当前对话中已读取的 Tower 事实、用户模式选择和资料范围，从现有状态继续。
4. 不复制旧流程，不同时维护第二套模板、状态机或平台采集规则。

最终输出和完成条件均以 `requirement-collection` 为准。
