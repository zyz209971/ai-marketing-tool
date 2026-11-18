# 技术方案
输入：spec.md。增量沿用 Python/FastAPI/Pydantic/LangGraph/SQLAlchemy 与原生 JavaScript。

## 架构
消息/API → 模型意图提取 → 数据/工具检查 → InputRequest → 前端选项或自由输入 → AnswerInput → 版本检查 → 下一轮图执行。
资料草稿走原 intake；策略审批走原 confirm，不把普通回答当批准。
questions.py 只根据后端确定的 pending_fields 生成可回答请求；事实类无猜测选项。
store.py 事务内检查 question_id、expected_revision、request_id；输入结果沿用既有任务快照。

## 持久化决策
本次保留现有“结束本轮、保存业务状态、下轮重新进入图”的恢复方式；不额外加入 interrupt/Command 的第二套权威状态。
刷新/进程重启后等待用户的问题仍在 SQL；执行中断的模型调用仍标失败，禁止盲目重放付费调用。
这是持久化业务状态恢复，不宣称从 LangGraph 任意节点精确恢复。以后替换执行模型时单独迁移。

## 知识和记忆
retrieval.py 适配 rag.search_marketing；data.context 读取已确认品牌知识及 studio.memory_context。
content.py 分开传品牌事实与风格案例，保存来源。销售与成本仍由 business.py 查询计算。
knowledge_index.py 在确认事务之后索引审核文本，失败不撤销事实确认。当前同步调用适合低并发；规模扩大后转作业队列。
memory.py 保存用户明确确认的长期语气；旧记忆管理仍负责编辑删除。

## 兼容和回滚
新增 API/任务 JSON 字段；旧消息入口、旧任务均可使用。新表 kb_index_status 只记录派生状态。
没有删除或覆盖现有数据库。回退代码可保留新增 JSON 字段/索引状态表；历史 RAG 使用独立副本。

## 公网前置条件（本次不实施）
取消硬编码共享工作区，补用户鉴权与每表归属校验；PostgreSQL 迁移、Postgres checkpointer、持久文件卷、备份恢复验证、HTTPS。
