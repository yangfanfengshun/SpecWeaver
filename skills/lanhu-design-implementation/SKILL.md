---
name: lanhu-design-implementation
description: 在开发 Tower 或本地需求资料时主动发现 design-context.json，先查看蓝湖预览图，再按组件或区域查询规范化设计事实并据此还原页面。用户要求“开发这个 Tower 需求”“按需求文档实现”“照设计稿还原页面”或修改带有蓝湖设计上下文的前端界面时使用。负责设计证据消费与视觉回归，不负责重新收集需求。
---

# 蓝湖设计实现

## 边界

- 只在用户明确要求开发或修改代码时使用；资料收集阶段不得提前进入本 Skill。
- Tower 决定业务和交互，Eolink 决定 API 契约，蓝湖决定可见视觉事实。
- 预览图用于理解整体，规范化 JSON 用于查精确值；不要通读或复制整个大型 JSON。
- 不重新选择设计范围；上下文缺失或存在多个匹配需求时暂停并询问，不静默猜测。

## 1. 自动发现设计上下文

1. 从用户给出的 Tower ID、需求名称、`requirement.md` 路径或当前任务目录定位
   `docs/tower/<任务>/design-context.json`。
2. 只有一个匹配项时自动采用，不要求用户重复提供蓝湖链接。
3. 多个匹配项无法根据 Tower ID 或路径排除时，列出候选并暂停。
4. 验证上下文中的预览图、结构文件和切图目录真实存在；缺失时报告具体文件，不伪造。

## 2. 先看图，再查事实

对每张与开发范围相关的设计：

1. 先打开 `preview`，确认页面、状态、区域和整体视觉关系。
2. 根据当前实现范围定位组件或区域，不把整份设计 JSON 加载进上下文。
3. 使用 `scripts/query_design.py` 查询节点摘要：

```bash
python3 <skill-dir>/scripts/query_design.py <design-json> summary
python3 <skill-dir>/scripts/query_design.py <design-json> search --query "按钮文案"
python3 <skill-dir>/scripts/query_design.py <design-json> node --id "<node-id>"
python3 <skill-dir>/scripts/query_design.py <design-json> point --x 120 --y 360
python3 <skill-dir>/scripts/query_design.py <design-json> region --x 0 --y 300 --width 375 --height 120
python3 <skill-dir>/scripts/query_design.py <design-json> measure --from-id "<node-a>" --to-id "<node-b>"
```

4. 一次查询一个组件或区域所需的整组属性，避免按颜色、间距、圆角逐项碎查。
5. 对颜色、字体、字号、行高、尺寸、间距、圆角、边框、阴影、裁剪、定位和资产存在
   精确值需求时必须查询，不能只凭预览图估算。
6. 查询结果仍不明确时再读取目标节点附近的小段 JSON；区分 `fact` 与 `derived`。

## 3. 实现与回归

1. 先遵循目标仓库现有组件、样式和资源约定，再应用查询到的设计事实。
2. 优先使用 `design-context.json` 指向的真实切图，不重画已有资产。
3. 完成页面后运行与改动相称的检查，并在条件允许时生成实现截图。
4. 将实现截图与蓝湖预览图比较；对差异区域再次按组件、节点或坐标查询后修正。
5. 无法自动截图时明确说明未完成视觉对比，不把代码检查通过描述成还原验证通过。

完成后报告采用的设计上下文、查询过的关键区域、验证结果和仍无法确认的视觉细节。
