# 本地验收与部署准备

状态：已提供配置与迁移工具，本轮没有发布公网。当前机器未安装可用 Docker/PostgreSQL，不能把下述容器与真实 PG 运行视为已验收。

## 继续本地使用

在项目根目录执行 `./start-agent.ps1`，打开 `http://127.0.0.1:8021/agent.html`。模型配置继续放在 `backend/.env.local`，不提交 Git；当前本机模式无需登录。

本机业务数据在 `.local-data/agent/brand-knowledge.db`，图状态在 `agent-checkpoints.db`，附件在 `brand-files/`。这些文件共同构成运行数据，不能只备份其中一个。旧营销案例索引仍是单独的 `marketing.db`。品牌已确认知识存入 `kb_chunks`，只有配置独立 Embedding 服务才产生向量；没有向量时仍进行文字检索。

本机启动器强制将业务库和checkpointer放在指定runtime，忽略私有模型配置中可能存在的远端数据库地址。PostgreSQL使用专门的部署入口。可运行 `.venv/Scripts/python.exe backend/scripts/smoke_restart_local.py` 验证独立进程重启与整套本地快照恢复；脚本不读取模型Key，也不操作正在使用的8021服务。

## 容器预演（有 Docker 的机器上）

1. 将 `deploy.env.example` 复制为 `.env.deploy`，填写随机数据库密码；真实模型填写 Key、模型名并设 `USE_MOCK=false`。该私有文件已被 Git/Docker 忽略。
2. 先停占用 8021 的本地服务，再运行 `docker compose --env-file .env.deploy up --build -d`。
3. 交互式创建账号：`docker compose --env-file .env.deploy exec api python backend/scripts/manage_account.py student01 --workspace team-a`。密码在提示中填写，不放入命令或 Git。不同 workspace 隔离资料，同 workspace 账号共享该品牌空间。
4. 打开 `http://127.0.0.1:8021/login.html`。分别用两个工作区测试，确认互相看不到品牌、对话和附件。

Compose 只绑定 `127.0.0.1`，数据库无宿主机端口。当前 HTTP Cookie 例外仅为本机预演。正式上线须先选定服务器及 HTTPS 反代，并设置 `COOKIE_SECURE=true`、`ALLOW_LOCAL_HTTP=false`；本轮不做这一操作。

## 存储与运行边界

| 内容 | 本地 | 部署配置 |
|---|---|---|
| 品牌、产品、经营数据、已确认偏好、任务快照、版本与审批 | SQLite 业务库 | PostgreSQL，`BRAND_DATABASE_URL` |
| LangGraph 节点位置、等待问题、恢复记录 | SQLite checkpointer | PostgreSQL，`AGENT_CHECKPOINT_URL` |
| 上传原文件、生成素材 | 本地目录 | 持久文件卷 |
| 旧营销参考案例 | 独立 SQLite 索引 | 仍独立；仅导入获准共享的参考资料 |
| 登录账号/会话 | 账号模式可用；本机默认关闭 | 同业务数据库；密码派生哈希、随机会话令牌哈希 |

环境变量优先，后端私有文件作为本地便利层。前端不接收模型 Key。数据库密码不在 URL 模板中手拼，启动脚本按两个驱动的格式生成。

一个 Uvicorn 进程、两个 Agent 执行线程、最多八个排队/执行请求。不要增加 worker 或 API 副本：当前启动恢复逻辑与任务所有权尚不是分布式设计。执行过程中重启会标记该轮失败，禁止自动重放可能收费的调用；已进入等待的任务可正常恢复。业务库和图状态之间没有跨库原子事务，界面任务快照是权威输入，恢复用后端已校验状态覆盖。

## 本地数据迁移

先停源服务和目标 API，数据库保持运行。快照命令只复制，拒绝有正在执行任务的源库和已存在的目标目录：

```powershell
.venv/Scripts/python.exe backend/scripts/snapshot_runtime.py --runtime .local-data/agent --destination .local-data/backups/agent-20261118
```

在配置了目标环境变量的机器上，执行 `python backend/scripts/migrate_runtime.py --snapshot <快照目录>`。目标必须是本程序初始化后、业务表及图记录均为空的新数据库，附件目录也必须为空。容器使用时将快照只读挂载到 `/snapshot`，再用 `docker compose ... run --rm --no-deps -v <快照绝对路径>:/snapshot:ro api python backend/scripts/migrate_runtime.py --snapshot /snapshot`。

迁移保留 workspace、品牌 ID、任务、记忆、版本、待确认问题及 checkpoints；不会重归属给新账号。旧本机资料属于 `local-preview-workspace`，只有明确分配此 workspace 的账号能访问。迁移成功后才创建新账号和启动 API。

不迁移旧登录会话、限流计数、历史破坏性归并档案，也不自动导入 `marketing.db`；未知表或未完成执行会阻止迁移。迁移过程中数据库、checkpoint 和附件不是一个事务，失败后不要启动目标服务或覆盖源；保留源快照，换一个全新的空目标再排查。迁移函数在 SQLite 替身上验证了拒绝覆盖、源不变及 interrupt 恢复；真实 PostgreSQL 路径仍须实机演练。

## 备份与恢复

本地使用上面的停机快照；恢复时复制整套数据到新的 runtime，通过 `start-agent.ps1 -Runtime <新目录>`（或 `run_agent_local.py --runtime <新目录>`）启动验证，不覆盖原目录。

容器备份：停止 API 后，在 db 容器内运行 `pg_dump -U brandpilot -d brandpilot -Fc -f /tmp/brandpilot.backup`，用 `docker compose cp db:/tmp/brandpilot.backup <备份目录>` 取出；同时归档 files 卷。用容器文件复制，避免旧 PowerShell 二进制重定向破坏备份。恢复到新数据库/新卷，使用 `pg_restore --no-owner`，先验证等待任务恢复及文件下载，再切换服务。不要执行删除卷的命令来“重试”。

## 正式发布前尚须验证

- 容器构建、PostgreSQL/pgvector、真实迁移、重启恢复和备份恢复演练。
- HTTPS、Cookie、反代与来源检查；管理员账号交付，模型额度和超时。
- 小规模并发与日志保留；当前认证提供工作区边界，没有完整角色管理、找回密码或跨设备会话管理界面。
- 当前仍是课堂规模工程；每用户模型预算、分布式队列和持续评测不是本轮已交付能力。

持久化实现对照：[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[interrupt/resume](https://docs.langchain.com/oss/python/langgraph/interrupts)。代码以仓库固定的依赖版本为准。
