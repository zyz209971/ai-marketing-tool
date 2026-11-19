# update.zip 使用说明

打包日期：2026-11-18（Asia/Shanghai）。类型：可提交 GitHub 的完整源码快照 / 部署候选版。

## 先看这三件事

1. 本包包含当前本地未提交的改动，不只是旧 Git 提交。来源分支及基线提交记录在 RELEASE_MANIFEST.json。不是最新 main 的证明，也不是 Git 补丁。
2. 适合放到功能分支供团队审查；解压到新目录，按文件审查并合入已有仓库。不要直接把 ZIP 当作线上目录覆盖，不携带或替换原仓库的 .git。
3. 本包不是已完成生产验收的镜像。当前机器没有 Docker/PostgreSQL 实机验证；部署步骤以 docs/deployment.md 为准。

## 包含与排除

包含当前 frontend、完整 backend、测试、部署入口与 Docker/Compose、空密钥模板、SDD 规格及仓库内 Spec Kit 开发流程、数据准备案例，以及仓库已跟踪的 RAG 参考 JSONL/CSV。

不包含 .env / .env.local / .env.deploy、API Key、数据库、会话、账号、上传文件、生成作品、虚拟环境、依赖目录、日志、截图、构建缓存或 .git 历史。不包含旧 frontend-v2、副本部署脚本 deploy.sh 和无关的历史根目录报告。完整排除清单见 RELEASE_MANIFEST.json。

部分 README 保留早期实现介绍；当前界面、后端持久化与功能边界以 docs/product-requirements.md 和 docs/unified-workbench-20261118.md 为准，根目录带日期文档保留作历史参考。

已有文档中的历史路径是说明，不代表本包包含对应本机数据。本包不会把用户的 16 个本地任务或真实品牌工作库上传到 GitHub。

## 本地启动

Windows / Python 3.12 建议步骤（在解压目录）：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-agent.txt
# 仅在没有私有配置时复制模板；不要覆盖自己的配置
Copy-Item backend/.env.example backend/.env.local
./start-agent.ps1
```

模型 Key 只填写到 backend/.env.local。模板中的模型名及服务地址需与你实际获准调用的模型对应。前端不填写 Key。无 Key 会显示演示模式；主界面 http://127.0.0.1:8021/。

新环境默认没有真实品牌、商品和对话。从对话上传资料建立品牌，按 docs/marketing-data-guide.md 完成补问、确认和经营表导入。

## 部署入口

1. 将 deploy.env.example 复制为私有 .env.deploy，填写随机 DB_PASSWORD、实际 AGENT_API_KEY/BASE_URL/MODEL 和文案模型，设 USE_MOCK=false。
2. 先在本机预演：docker compose --env-file .env.deploy up --build -d。
3. 创建账号：docker compose --env-file .env.deploy exec api python backend/scripts/manage_account.py student01 --workspace team-a。密码按交互提示输入，不写进命令或 Git。
4. 对外服务前配置 HTTPS 反代，保留 Host，设置 COOKIE_SECURE=true、ALLOW_LOCAL_HTTP=false；模板的非安全 Cookie 仅为本机 HTTP 预演。Compose 默认只绑定 127.0.0.1，数据库不暴露宿主端口。
5. 使用一个 API 进程；不要加 worker/多副本，现有任务执行所有权不是分布式设计。数据库、checkpoint 和附件卷要成套备份并演练恢复。

必须补验：容器构建及依赖安装、PostgreSQL/pgvector/图状态持久化、重启与恢复、跨工作区隔离、HTTPS Cookie 与反代、真实模型调用及小规模并发。并非打出 ZIP 就已完成这些验收。

## RAG 和数据

RAG 代码保留。backend/data/*.jsonl 和根目录 CSV 是仓库参考源，不是已核实的当前品牌售价，也不会自动成为品牌事实。Docker 镜像不打包这些数据；知识库初始为空。用户品牌以确认上传为准。

需要恢复营销参考索引时，使用获准的源资料在独立目录重建，再按 docs/deployment.md 导入持久卷。代码路径 backend/scripts/update_marketing.py 支持显式文件路径；指定 APP_DATA_DIR，避免误写当前工作库。不要把私有运行库提交到 GitHub。

## 验证

已从 ZIP 解压到新目录重新验证：Agent 等后端测试 96 项、品牌知识库 17 项、前端 12 项全部通过；前端构建和隔离离线服务的浏览器完整流程通过。验证使用本机已安装的 Python/Node 依赖；未做全新环境 pip 安装、Docker 构建或真实 PostgreSQL/HTTPS 验收。

代码当前的验收记录：docs/unified-workbench-20261118.md。打包验证的结果见 RELEASE_MANIFEST.json。

```powershell
cd frontend
npm test
npm run build
cd ../backend
../.venv/Scripts/python.exe -m pytest tests/test_marketing_agent.py tests/test_task_paths.py tests/test_workbench.py tests/test_marketing_case.py tests/test_environment.py tests/test_deployment_config.py -q
# 知识库测试须另一个进程，避免模块级环境变量/数据库互相污染
../.venv/Scripts/python.exe -m pytest tests/test_knowledge.py -q
```

RELEASE_MANIFEST.json 记录每个文件的 SHA256；ZIP 外附 update.zip.sha256。GitHub 推荐提交解压后的源码、模板、测试和文档；ZIP 是交接件，不代替代码审查和 PR。
