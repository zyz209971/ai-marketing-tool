# Data Model

浏览器使用 compose:<taskId> 保存草稿文字，agent-batch:<taskId>:<questionId> 保存问题选项，agent-send:<taskId> 保存 SendAttempt{action,payload,draft,answers,state,runId,checkedAbsent?}。payload 为深复制的原提交体，包含 request_id、expected_revision、文字与有效选项；重试不能修改该原提交体。任务归属由存储键确定，不存密钥。

失败恢复不覆盖非空的新输入；确认接收仅清理与发送内容匹配的输入，不清理快捷指令旁未发送的其他文字。忙碌期间禁止切换对话或重复提交。商品关联持久化在服务端 Brief.sku_id，不再依赖 compose-context 临时缓存；旧对话未绑定商品时需重新选择商品入口。

服务端沿用 agent_runs(task_id,request_id,request_hash) 唯一键，不迁移表。接收凭据读取先验证工作区及任务归属，仅返回 found、run_id 与 status。
