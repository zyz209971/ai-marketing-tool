# Implementation Plan: 商品选择到对话的可靠传递
**Branch**: fix/product-context-handoff | **Date**: 2026-11-23 | **Spec**: [spec.md](spec.md)
**Base**: f9af22cca1ed00062fcfefdaa8a646d89be6603a
**Status**: 用户于2026-11-23确认方案；实现与自测完成，等待用户验收。

## Summary
顶部入口读取跨页bulkIds选择；零款走原通用入口，一款传SKU，多款明确提示。创建对话时服务端校验并把SKU写入Brief，摘要显示商品与规格。卡片入口使用同路径；预填文字不再是关联成立的条件。

## Technical Context
原生JavaScript ES modules；Python 3.12本地、FastAPI与现有LangGraph运行时；不新增依赖或前端构建链。业务库使用现有服务抽象，本地SQLite，保持PostgreSQL路径兼容。浏览器草稿沿用sessionStorage。Node纯逻辑测试与后端pytest分模块运行；浏览器交互仅使用当前会话可用且获准的浏览器工具，基础设施不可用则如实列未测。无需调用真实模型或Embedding。
范围仅为本规格，不改变优惠计算、模型输出、资料/偏好内容。创建和查询接口向后兼容，不做数据库迁移。

## Constitution Check
设计前/设计后均通过：保留框架；可信商品服务不改；确定性验证；任务与长期记忆分离；批准门禁不改；私有数据不进Git；规格、计划、后续任务和验收证据依序执行。无例外。不存在未解技术澄清；业务范围遵循已确认规格。

## Project Structure
frontend/src/app.js（入口与多选边界）；frontend/src/workbench.js（事件转发）；frontend/src/agent.js（创建参数与摘要）；backend/app/marketing_agent/contracts.py、api.py、store.py（可选SKU及授权校验）；相应前后端测试。
本目录增加research.md、data-model.md、contracts/interaction.md、quickstart.md。tasks.md仅在方案确认后生成。

## Detailed Design
1. app.js新增有边界的产品库创作处理：从当前品牌有效商品集合核对选择，保留选择，不静默取第一款。
2. workbench事件继续传brandId/skuId/text。
3. CreateConversation新增可选sku_id，api调用store.create_task的可选参数。先在授权品牌快照/目录内验证SKU有效且未归档，再创建状态，失败不创建空任务。
4. 初始Brief写入sku_id；现有接口返回catalog，任务摘要读取它展示名称与规格。
5. createAgent传sku_id；删除依赖context.text===body.text才能关联的旧机制，预填文字只用于表达，不作为身份。
6. 导航/刷新读取服务端Brief；只要用户未明确切换/清空商品，编辑输入不影响关联。用户后续明确商品变更仍经现有补丁校验，不强行注入旧SKU。

## Compatibility and Collaboration
POST /api/agent/conversations 新增可选 sku_id。旧 {brand_id,demo} 请求行为不变。带sku_id必须指定可访问品牌并验证商品在用；不能关联其他品牌、归档或不存在SKU。返回的state.brief.sku_id表示实际绑定，catalog提供展示资料。workbench:compose沿用brandId/skuId/text，不新增多商品能力。
与另一个修复共享agent.js，先完成005再串行接入006，避免互相覆盖。后端新增字段/只读接口需在PR告知Agent/前端维护成员，不改已有字段含义和业务公式。

## Validation
前端：零/一/多选择、跨页隐藏选择、卡片入口、文字编辑不丢关联。后端：创建绑定SKU、未带SKU兼容、跨品牌/失效/归档拒绝且不创建任务。浏览器：两款不同规格商品，两个入口各创建对话、编辑预填、导航和刷新、发送后不重复询问商品，未发送前不产生模型调用。
各项首先补能暴露旧行为的回归检查，修复后执行。完整后端按AGENTS逐模块；前端纯逻辑检查。记录截图、未测项及Git tree验收快照。该计划不表示检查已执行。

## Acceptance and Release
依团队流程完成任务后展示本地地址与步骤，停等用户“验收通过”。提交内容tree必须与验收快照一致；后续依CI/head绑定规则处理PR。当前不提交、不推送、不部署。数据不删除、不重置。

## Complexity Tracking
无框架、部署和数据库表结构新增；只添加必要字段/读取接口及可测试纯逻辑模块。
