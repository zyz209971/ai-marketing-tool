# 任务与验收
- [x] T001 官方 Spec Kit 配置与本功能规格。
- [x] T002 结构化问题、回答校验及持久化。
- [x] T003 前端补充卡、选项与自由输入；保留配色。
- [x] T004 接回旧营销检索、记录参考来源。
- [x] T005 确认后索引与关键词降级。
- [x] T006 长期记忆读取及明确保存边界。
- [x] T007 后端回归、前端和浏览器验收，证据见 validation.md。

后续独立规格（不计入本期完成度）：
- [ ] T101 独立品牌介绍文案路径，不要求促销字段。
- [ ] T102 真实模型质量评测集、语义越界检测与检索调优。
- [ ] T103 用户授权隔离、PostgreSQL/pgvector 迁移、备份恢复、HTTPS 后再开放公网。
- [ ] T104 对话摘要、长期偏好冲突合并、后台索引任务。


## 需求与实现映射
- T002 → FR-001～FR-005；backend/app/marketing_agent/{contracts,questions,store,graph}.py。约束依据 data-model.md 中 InputRequest.id/task_id/fields/choices、AnswerInput.request_id/expected_revision/question_id/choice_id/text。
- T003 → FR-002/FR-004；frontend/src/agent.js、agent.css。
- T004 → FR-006/FR-007；backend/app/marketing_agent/{retrieval,content}.py；artifacts.retrieval 的定义见 data-model.md。
- T005 → FR-008；backend/app/knowledge_index.py、knowledge.py；kb_index_status 定义见 data-model.md。
- T006 → FR-009～FR-011；backend/app/marketing_agent/{memory,data,content}.py；kb_memories 及来源定义见 data-model.md。
