# 选型记录
1. 用户确认的最小改动优先：不换框架，不引入额外 Agent。
2. 当前 SQL 业务快照已经包含暂停阶段，采用结构化问题请求完善它；本期不混用 LangGraph interrupt 与业务双重状态。
3. 旧 marketing.db 是 SQLite 文本索引，可直接复用；抽样历史库 1793 chunks，0 embedded。向量化不是复用前提。
4. 当前默认本地启动器固定 SQLite，不承诺设置 BRAND_DATABASE_URL 就完成 PostgreSQL 迁移。
5. Spec Kit 使用官方 specify-cli 1.4.2，在 .local-data/spec-kit-bootstrap 初始化 Codex skills + PowerShell，再仅复制新增 .specify 和 .agents，避免强制覆盖。
来源：https://github.github.io/spec-kit/how-to/existing-projects.html
来源：https://docs.langchain.com/oss/python/langgraph/interrupts
