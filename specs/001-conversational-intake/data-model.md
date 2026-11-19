# 数据模型与归属
- agent_tasks.state：本任务 messages、brief、strategy、approvals、artifacts、input_request；revision 是并发令牌。
- InputRequest：id/task_id/fields/question/reason/choices/allow_free_text/attachment_id。
- AnswerInput：request_id/expected_revision/question_id，choice_id 或 text 二选一；客户端不能自行指定选项 patch。
- kb_memories：品牌长期偏好；source task 在任务消息 memory_id 记录。已有编辑/删除操作生效。
- kb_chunks：确认版本的检索片段；embedding 可空。kb_index_status 标识 lexical_only/ready/embedding_failed。
- marketing.db：历史营销参考，只按营销类型检索，不把旧产品自动导入品牌事实。
- artifacts.retrieval：marketing_status、marketing_refs、memory_refs；source_refs 继续记录品牌来源。
- brand-files：上传原文；agent-checkpoints.db：执行快照；两者不替代业务权威状态。
本地单工作区，品牌 ID 区分知识。尚不具备用户/租户授权隔离。
