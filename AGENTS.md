# AGENTS.md — 任何 AI 或开发者改代码前必读

本文件是仓库级开发约束的入口。产品功能边界见 [docs/product-requirements.md](docs/product-requirements.md)；项目约束宪法（7 条，与本文一致）见 [.specify/memory/constitution.md](.specify/memory/constitution.md)。

## 架构速览

- 后端：FastAPI（`backend/app/`）。`marketing_agent/` 是营销智能体运行时（LangGraph 式图执行）。
- **双库分工**：PostgreSQL+pgvector（`marketing_agent/store.py`、`knowledge.py`）管账号/工作区/品牌事实/任务状态；SQLite（`backend/app/rag.py`）管营销案例 RAG（FTS5+n-gram+可选 embedding，可降级）。`DATA_DIR` 统一管理数据目录。
- 前端：`frontend/` 原生 JS 静态页面，由后端直接托管，**没有前端构建链**。

## 命令速查

```bash
# 本地环境（Windows 用 start-agent.ps1；跨平台用下面两行）
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements-agent.txt
python backend/scripts/run_agent_local.py        # 主界面 http://127.0.0.1:8021/

# 测试（注意：各模块的临时库在模块级创建，混跑单进程会互相干扰——按模块逐个跑）
cd backend && for f in tests/test_*.py; do python -m pytest "$f" -q || break; done   # 后端，113 项
node --test frontend/tests/*.test.mjs            # 前端纯逻辑测试
# frontend/tests/*-browser.mjs 是 E2E 预演脚本：需先启动服务并安装 Playwright，CI 不跑

# 数据（源文件在 Git，数据库是本地生成物）
python scripts/import_csv.py ../产品知识库.csv                       # 改了产品 CSV 后
python scripts/update_marketing.py ../marketing                      # 改了营销案例后（--append 追加）

# 发布快照基线
python scripts/make_release_manifest.py          # 重新生成 RELEASE_MANIFEST.json
```

模型密钥只写在 `backend/.env.local`（本地）或 `.env.deploy`（部署），从 `.env.example` 复制模板，**绝不提交**。

## 铁律（红线）

1. **密钥与生成物不进 Git**：`.env*`、`*.db`、私钥、日志、上传文件。CI 有门禁拦截。
2. **源文件/生成物分离**：改数据只改 `产品知识库.csv` 和 `marketing/`，改完跑导入脚本；不要手改数据库。
3. **单 API 进程**：任务执行所有权不是分布式设计，禁止加 worker/多副本/`replicas>1`。
4. **生产模型是百炼，本地可能不同**：模型配置只走环境变量（`AGENT_*`/`WORD_*`/`COPY_*`/`EMBED_*`），代码里不写默认端点；**更换 embedding 模型后必须重建 RAG 索引**（旧模型向量会被自动忽略并降级为词法检索）。
5. **前端不引入构建链**：保持静态托管。
6. `SEED_DEMO_DATA` 保持默认 false，生产环境禁止自动植入示例数据。
7. **改动一律走 功能分支 → PR**（模板见 `.github/PULL_REQUEST_TEMPLATE.md`），不直推 main。新功能先用 Spec Kit 建 spec（`specs/`，工具在 `.specify/`，Windows 用 PowerShell 脚本）。

## 禁改清单（改动需在 PR 中给出充分理由）

- `.specify/` 的脚本与模板（Spec Kit 工具本体）
- `Dockerfile`/`compose.yaml` 的安全默认值：非 root 用户、只绑 127.0.0.1、数据库不暴露宿主端口、单 api 进程
- `backend/scripts/check_repo_safety.py`（推送前密钥扫描）
- `.gitattributes`/`.gitignore` 的排除规则

## 文档地图

README（快速上手）→ docs/product-requirements.md（功能边界）→ docs/marketing-data-guide.md（数据准备）→ docs/deployment.md（部署）→ docs/release-checklist.md（上线清单）→ docs/deploy-cutover.md（旧服务切换手册）→ specs/（SDD 规格档案）→ docs/history/（历史文档存档）
