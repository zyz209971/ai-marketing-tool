# 顺序任务
- [x] T01 本功能spec/plan/data-model，替代001中的后置决定（FR-001～008）。
- [x] T02 增加失败验收测试（批量/部分回答/上传继承/中断/隔离）。
- [x] T03 contracts/questions/intake/graph/store：批次与意图处理（FR-001～004；data-model.md QuestionBatch、Question、BatchAnswer）。
- [x] T04 frontend agent/workspace：统一输入/编辑保存/摘要（FR-005）。
- [x] T05 graph/api：interrupt、Command与checkpointer（FR-006）。
- [x] T06 auth/workspace/knowledge/store：身份及隔离，停止共享归并（FR-007；data-model.md auth_users、auth_sessions、agent_tasks.workspace_id）。
- [x] T07 PostgreSQL/checkpointer/迁移/容器配置/备份文档（FR-008）；真实PG验收待环境，不计为已验证。
- [x] T08 全部回归、浏览器、真实模型抽验、记录未验证边界。
- [x] T09 收尾验收：真实子进程重启/本地快照恢复；本机启动强制隔离远端checkpointer；同步证据。

## 环境具备后的独立验收
- [ ] Docker构建、真实PostgreSQL迁移与备份恢复、HTTPS及小规模并发演练。当前无引擎，本轮不发布公网。
