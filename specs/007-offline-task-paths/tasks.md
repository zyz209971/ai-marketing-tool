# Tasks: 第二轮离线修复

## Setup
- [x] T001 核对独立分支、基线、规格/方案确认和忽略规则，保留第一轮工作区。
- [x] T002 在 backend/tests/test_offline_paths.py 添加五项失败回归及边界。

## US1 / OFF-01
- [x] T003 在 backend/app/marketing_agent/offline.py 实现有界明示字段解析，接入 organization.py 与 intake.py，保留草稿与证据。
- [x] T004 验证同行/逐行、多商品、矛盾字段、不猜定位和离线限制引导。

## US2 / OFF-02 / OFF-03
- [x] T005 在 model.py、offline.py 修复单位任务意图、成本字段别名与严格金额，沿用原单位工具。
- [x] T006 在 business.py、contracts.py 增加可选pair_variable_cost_minor（data-model.md EvaluationData.pair_variable_cost_minor），前端agent.js展示完整单位数值，同步接口文档。
- [x] T007 验证27/16/11元、成本追问、非法金额、单位与活动对照及旧句式。

## US3 / OFF-04 / US4 / OFF-05
- [x] T008 在 offline.py、model.py、content.py 分离具体标题、可复用风格和编辑范围。
- [x] T009 在 graph.py实现离线无变化/不支持改写提示，不增加假版本；验证归档和正文不变。
- [x] T010 验证一次性指令不进style或长期记忆，旧风格修改、活动条款回归。

## Validation
- [x] T011 后端按模块及前端检查，隔离本地服务与浏览器验收，记录截图和未测项到validation.md。
- [x] T012 集成最新main检查、记录验收tree与地址，停等人工验收，不提交推送部署。

## Dependencies
T001→T002→T003/T004→T005/T006/T007→T008/T009/T010→T011→T012。文件共享部分串行修改；测试文件间可独立运行，本轮不委派代理。确认方案仅推进实施，本地验收通过才可提交。
