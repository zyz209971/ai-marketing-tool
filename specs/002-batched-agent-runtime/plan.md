# 技术计划
保持 FastAPI/LangGraph/原生JS/暖色样式，借鉴Codex questions[]协议，不移植Rust运行时也不整体迁移React。
按次序：T01规格→T02失败验收测试→T03批次/意图与草稿→T04界面→T05interrupt→T06工作区→T07Postgres/部署配置→T08回归验收。
批次规划按任务依赖，模型理解自然语言，后端决定允许字段与缺失闸门。兼容旧单题字段与messages入口。
图终点改为prepare_wait→await_input(interrupt)，恢复后接收后端校验的用户输入，回到业务路由。await节点不做模型调用/写外部资源。
业务任务快照是界面投影/版本闸门；checkpoint保存执行位置；已确认品牌事实/审批/作品仍在业务库。附件确认作为独立事务之后同步新的图输入。
认证使用持久化不透明session、密码派生哈希、同源校验；ContextVar将workspace传入现有服务与线程。legacy数据保留本机workspace，不自动分配给新账号。
部署使用单服务进程+PostgreSQL/pgvector+持久文件卷；不引入Redis/K8s。无本机PG引擎时明确记录仅配置及契约验证。
