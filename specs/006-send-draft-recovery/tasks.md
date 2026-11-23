# Tasks

## Setup and user stories
- [x] T001 [US1] 在 frontend/tests/send-state.test.mjs 添加草稿失败恢复测试
- [x] T002 [US2] 在 store.py、api.py 增加授权接收凭据查询并测试
- [x] T003 [US1] 在 send-state.js 实现发送尝试持久化与新旧隔离
- [x] T004 [US2] 在 agent.js 分开提交、接收核查和执行轮询
- [x] T005 [US3] 验证问题选项/刷新/新输入/存储故障边界
- [x] T006 在 validation.md 记录自测与快照，等待人工验收

## Dependencies
按T001→T006顺序；005先于006。接口测试与前端纯逻辑测试可独立运行，但不委派代理。
## Delivery
最小修复和防回归完成后逐步验收；未经人工验收不提交。
