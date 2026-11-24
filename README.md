# BrandPilot · AI 营销素材生成工具（统一工作台）

面向电商运营 / 校园商家的营销素材生成工具：从品牌资料与经营事实出发，通过对话式智能体生成多平台营销文案与海报，全部活动主张可追溯到已确认的数据。

> 当前主入口为统一工作台（对话 + 管理 + 品牌工作区），会话登录、多工作区隔离。功能边界见 [docs/product-requirements.md](docs/product-requirements.md)。
> **改代码前先读 [AGENTS.md](AGENTS.md)**（命令、铁律、禁改清单）。

## 快速开始（本地）

需要 Python 3.12+。

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-agent.txt   # macOS/Linux: .venv/bin/pip
cp backend/.env.example backend/.env.local                    # 填入你的模型 Key（不进 Git）
python backend/scripts/run_agent_local.py                     # Windows 也可直接 ./start-agent.ps1
```

打开 http://127.0.0.1:8021/ 。没有模型 Key 时自动进入演示模式（模板文案 + 占位图）。新环境默认无品牌数据：从页面上传品牌资料建档，或按 [docs/marketing-data-guide.md](docs/marketing-data-guide.md) 准备。

## 测试

```bash
python -m pytest backend/tests          # 后端
node --test frontend/tests/*.test.mjs   # 前端纯逻辑（*-browser.mjs 为本地 E2E 预演，需起服务+Playwright）
```

## 更新数据（团队同学看这里）

- 改产品（价格/卖点）：改 `产品知识库.csv` → `cd backend && python scripts/import_csv.py ../产品知识库.csv`
- 改营销案例：案例放入 `marketing/` → `python scripts/update_marketing.py ../marketing`（追加加 `--append`）
- 改经营数据：改 `合成数据+人工答案+商品图片+csv+json/` 中的 SKU 映射、成本或订单 → `python scripts/import_operations_dataset.py "../合成数据+人工答案+商品图片+csv+json" --brand-id <品牌ID>`
- 生成看板案例：`python scripts/generate_dashboard_fixtures.py`，输出在 `.local-data/dashboard-fixtures/`，不进 Git
- 数据库（`*.db`）是本地生成物，不进 Git；谁改源文件谁重建。

## 部署

Docker Compose（PostgreSQL+pgvector，仅绑定回环地址）：

```bash
cp deploy.env.example .env.deploy   # 填 DB_PASSWORD 与百炼等模型配置，USE_MOCK=false
docker compose --env-file .env.deploy up --build -d
```

完整步骤、账号创建与 HTTPS 要求见 [docs/deployment.md](docs/deployment.md)；上线前逐条过 [docs/release-checklist.md](docs/release-checklist.md)；从旧 systemd 部署切换见 [docs/deploy-cutover.md](docs/deploy-cutover.md)。

## 文档地图

[AGENTS.md](AGENTS.md) 开发约束 · [docs/product-requirements.md](docs/product-requirements.md) 功能边界 · [docs/marketing-data-guide.md](docs/marketing-data-guide.md) 数据准备 · [docs/model-configuration.md](docs/model-configuration.md) 模型配置 · [docs/deployment.md](docs/deployment.md) 部署 · [specs/](specs/) SDD 规格档案 · [docs/history/](docs/history/) 历史文档 · [RELEASE_MANIFEST.json](RELEASE_MANIFEST.json) 本轮导入基线（生成脚本 `scripts/make_release_manifest.py`）

## 协作方式

功能分支 → PR（按模板填自测清单）→ 合并 main。生产只从 main 部署。每个新功能先用 Spec Kit 写 spec（`.specify/`，见 AGENTS.md 命令速查）。
