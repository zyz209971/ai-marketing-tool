# Tasks

## Setup and user stories
- [x] T001 [US1] 在 backend/tests/test_handoff_recovery.py 与 frontend/tests/product-context.test.mjs 添加失败回归检查
- [x] T002 [US1] 在 contracts.py、api.py、store.py 校验并保存初始SKU
- [x] T003 [US1] 在 app.js、workbench.js、agent.js 统一入口和商品显示
- [x] T004 [US2] 验证编辑预填/导航/刷新仍使用服务端SKU
- [x] T005 [US3] 验证空选、多选、归档/跨品牌边界
- [x] T006 在 validation.md 记录回归结果和待人工验收项

## Dependencies
按T001→T006顺序；005先于006。接口测试与前端纯逻辑测试可独立运行，但不委派代理。
## Delivery
最小修复和防回归完成后逐步验收；未经人工验收不提交。
