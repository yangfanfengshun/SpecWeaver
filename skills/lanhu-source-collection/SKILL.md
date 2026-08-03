---
name: lanhu-source-collection
description: 从蓝湖读取项目与设计候选，并在范围确认后保存设计预览图、规范化图层结构和真实切图，按统一来源协议返回可追溯设计证据。用户提供蓝湖链接、要求收集或核对设计稿，或总控需求收集流程需要蓝湖资料时使用。不分析业务代码、不生成最终需求文档、不直接开始页面开发。
---

# 蓝湖来源采集

## 输入与边界

- 接收蓝湖项目/设计链接、采用范围，以及可选的绝对项目输出路径。
- 只负责蓝湖候选与设计证据；不决定需求模式，不生成最终 Markdown。
- 向总控返回结果时遵守
  [来源结果协议](../requirement-collection/references/source-result-contract.md)。

## 候选与认证

1. 调用 `lanhu_check_auth()` 确认能力状态。
2. `disabled` 表示本机未启用蓝湖能力，不等于无设计稿；立即返回，不继续询问或请求。
3. 调用 `lanhu_get_designs` 获取项目、分组和设计候选，不下载图片。
4. 只有调用方已确认唯一范围时才读取详情；存在多组或关联不明时返回候选与歧义，
   不自行选择。

认证失效时返回 `auth_expired` 并提示 `specweaver configure lanhu`；区分
`forbidden`、`network_error` 和 `not_found`，不得自动改成无设计稿。

## 收集已确认设计

对每张已确认设计按稳定 `image_id` 执行：

1. 调用 `lanhu_get_design_detail`，把完整规范化数据写入
   `~/.specweaver/cache/lanhu/<image_id>/<设计名称>--<image_id>.json`；设计改名时原子
   更新并清理旧名称文件。缓存键使用 `project_id + image_id` 识别来源，`version_id`
   记录当前版本。
2. 调用 `lanhu_download_design_images` 保存
   `images/<设计名称>--<image_id>-preview.<ext>`，并实际查看文件，确认它与设计 ID
   一致。
3. 调用 `lanhu_download_slices` 保存到
   `images/lanhu-slices/<设计名称>--<image_id>/`；共享设计缓存不写项目切图路径。
4. 保留设计名称、项目/设计 ID、来源 URL、画布尺寸、预览图、结构文件、切图目录和
   失败原因，供统一收集清单记录和后续分析使用。

## 结果要求

- `items` 只返回候选摘要或已确认设计摘要，不把完整图层树放入对话。
- `artifacts` 区分 `preview`、`design_facts` 和 `slice`；项目图片使用相对目标目录的
  路径，`design_facts` 使用用户缓存绝对路径。
- `provenance` 关联项目、设计、图层、远程资产与本地文件。
- 蓝湖直接提供的数据保留 `source: fact`；布局推导保留 `source: derived`。
- 预览图负责整体视觉理解，结构文件负责精确查询；不得仅凭视觉猜颜色、间距或字体。
- 不输出 Cookie、Authorization 或登录响应。

独立使用时返回设计证据摘要；除非用户明确要求进入开发，否则不调用
`lanhu-design-implementation`。
