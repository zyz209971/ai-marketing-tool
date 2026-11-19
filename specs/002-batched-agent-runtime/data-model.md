# 数据结构
QuestionBatch: id/task_id/questions[]/fields；兼容旧question/choices。Question: id稳定到字段组+附件、fields、question、reason、choices、status。
BatchAnswer: question_id沿用批次ID；answers映射每题ID到choice_id或text；旧choice_id/text兼容。expected_revision非负整数，request_id8-100字符，text最多5000。
agent_tasks: 增加workspace_id（历史默认local-preview-workspace），state增加input_request/suspended_attachment_id/checkpoint状态。
auth_users: username唯一/workspace_id/password_hash；auth_sessions: token_hash/username/expires；令牌明文仅cookie。任务运行通过task关联workspace。auth_attempts保存账号+来源的派生标识、失败次数和窗口起点。
提取模型内部协议：逐项返回Brief中除brand_id外的全部字段，未提及填null，显式清空列入clear_fields；后端只合并非空值及显式清空项。该模型协议不同于对外MessageInput.patch。
数据库: BRAND_DATABASE_URL、AGENT_CHECKPOINT_URL选择SQL后端；源文件持久卷、旧marketing.db仍是只读参考数据，不冒充已迁移pgvector。
