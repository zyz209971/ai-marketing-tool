# Implementation Plan: 发送失败的草稿与接收状态恢复
**Branch**: fix/product-context-handoff | **Date**: 2026-11-23 | **Spec**: [spec.md](spec.md)
**Base**: f9af22cca1ed00062fcfefdaa8a646d89be6603a
**Status**: 用户于2026-11-23确认方案；实现与自测完成，等待用户验收。

## Summary
引入按任务隔离的发送尝试状态，将预提交保护、接收确认和执行轮询分开。未接收恢复文字/选项/商品上下文；已接收仅恢复查询运行；不明结果通过后端已有幂等凭据核查，不自动新建请求。

## Technical Context
原生JavaScript ES modules；Python 3.12本地、FastAPI与现有LangGraph运行时；不新增依赖或前端构建链。业务库使用现有服务抽象，本地SQLite，保持PostgreSQL路径兼容。浏览器草稿沿用sessionStorage。Node纯逻辑测试与后端pytest分模块运行；浏览器交互仅使用当前会话可用且获准的浏览器工具，基础设施不可用则如实列未测。无需调用真实模型或Embedding。
范围仅为本规格，不改变优惠计算、模型输出、资料/偏好内容。创建和查询接口向后兼容，不做数据库迁移。

## Constitution Check
设计前/设计后均通过：保留框架；可信商品服务不改；确定性验证；任务与长期记忆分离；批准门禁不改；私有数据不进Git；规格、计划、后续任务和验收证据依序执行。无例外。不存在未解技术澄清；业务范围遵循已确认规格。

## Project Structure
frontend/src/agent.js（send/onsubmit/open/initialize/poll及恢复提示）；frontend/src/send-state.js（拟新增纯逻辑状态与存储适配）；必要的静态样式；backend/app/marketing_agent/api.py、store.py（只读接收凭据查询）；前端测试、后端权限/幂等测试。
本目录增加research.md、data-model.md、contracts/interaction.md、quickstart.md。tasks.md仅在方案确认后生成。

## Detailed Design
1. 统一send与answer入口，收集文字、有效选项、问题ID、任务ID、原expected_revision；在清空输入前保护快照。快捷入口也走同一路径。
2. request_id使用现有HTTP兼容生成方式，在发起网络请求前创建并存储；本地异常不会先删除草稿。
3. 发送尝试保存原请求体与状态prepared/submitting/unknown/accepted/rejected；仅有效接收响应带run_id后确认提交并清理对应草稿，生成结果不决定是否已发送。
4. 已接收后轮询失败保留run_id和查询入口，不把原消息重新填成待发送。运行失败提示执行失败，不冒充发送失败。
5. 超时/响应丢失为unknown。新增授权只读凭据查询，找到记录则转accepted；查不到不自动发送，以原request_id及完全相同请求体允许用户重试，复用enqueue现有去重。
6. 409/422等明确拒绝保留可编辑草稿；刷新任务/问题后让用户核对，有内容或expected_revision变化时新建逻辑操作，不能复用旧键配新请求。
7. 恢复限定同任务、同草稿版本；新输入不得被异步旧响应覆盖。保留原失败内容独立恢复入口。sessionStorage不可用时保留内存/输入并提示刷新恢复不可保证。
8. 发送乐观气泡要与真实消息协调，失败不残留伪成功或重试重复气泡。刷新读取pending发送状态后再决定恢复草稿还是查询运行。

## Compatibility and Collaboration
新增 GET /api/agent/conversations/{task_id}/submissions/{request_id}：先授权任务，返回 {found:false} 或 {found:true,run_id,status}，不暴露原请求内容。未知/越权任务按现有404行为处理，不能跨工作区查询。现有POST消息/回答响应、request_id去重及hash语义不变；相同key必须使用原operation与完整payload（含expected_revision）。本次不承诺外部供应商只计费一次。
与另一个修复共享agent.js，先完成005再串行接入006，避免互相覆盖。后端新增字段/只读接口需在PR告知Agent/前端维护成员，不改已有字段含义和业务公式。

## Validation
前端纯逻辑：预提交异常、明确拒绝、网络未知、成功接收后轮询失败、刷新恢复、旧响应/新输入隔离、存储故障、问题选项保留、成功后不恢复旧草稿。后端：凭据查询授权、未知操作、重复同payload同run、不同payload拒绝。浏览器故障注入：请求中断/503/响应丢失，检查草稿、气泡和运行数量。正常发送与旧入口回归。
各项首先补能暴露旧行为的回归检查，修复后执行。完整后端按AGENTS逐模块；前端纯逻辑检查。记录截图、未测项及Git tree验收快照。该计划不表示检查已执行。

## Acceptance and Release
依团队流程完成任务后展示本地地址与步骤，停等用户“验收通过”。提交内容tree必须与验收快照一致；后续依CI/head绑定规则处理PR。当前不提交、不推送、不部署。数据不删除、不重置。

## Complexity Tracking
无框架、部署和数据库表结构新增；只添加必要字段/读取接口及可测试纯逻辑模块。
