# 旧部署 → Docker Compose 切换手册（owner 执行）

旧生产：腾讯云 Ubuntu + `deploy.sh`（systemd 服务 `ai-marketing-tool`，宿主机 venv，SQLite）。
新生产：同机 Docker Compose（api + PostgreSQL/pgvector），见 `docs/deployment.md`。全程保留回滚能力。

## 0. 前置

- [ ] 新代码已合并 `main` 并通过 `docs/release-checklist.md` A/B 两组检查
- [ ] 服务器已安装 Docker 与 compose 插件；磁盘余量 ≥ 10G
- [ ] 选定维护窗口（导入与重建索引期间服务不可用）

## 1. 备份（切换前必做）

```bash
sudo systemctl stop ai-marketing-tool          # 停旧服务
sudo cp -a /path/to/repo/backend/.env ~/backup-env-$(date +%F)   # 旧配置（含旧模型 key）
cp -a /path/to/repo/backend/data ~/backup-data-$(date +%F)       # SQLite 库
sudo systemctl disable ai-marketing-tool       # 防止重启复活（不要 uninstall，留作回滚）
```

## 2. 拉取与配置

```bash
cd /path/to/repo && git fetch && git checkout main && git pull
cp deploy.env.example .env.deploy
# 按 docs/release-checklist.md B 组填写（百炼配置、DB_PASSWORD、USE_MOCK=false）
```

## 3. 启动与数据准备

```bash
docker compose --env-file .env.deploy up --build -d
docker compose --env-file .env.deploy ps       # 等 db healthy、api healthy

# 数据从源文件重建（不从旧 SQLite 搬库）
docker compose --env-file .env.deploy exec api python backend/scripts/import_csv.py /app/../产品知识库.csv || true
docker compose --env-file .env.deploy exec api python backend/scripts/update_marketing.py ../marketing
```

（如路径挂载不含源文件，可在宿主机以一次性容器挂载执行，或先 `prepare_production_data.py` 导出后传入。）

## 4. 验证与开放

- 按 release-checklist.md C/D 组逐条验证（重点：RAG 百炼索引、登录冒烟、工作区隔离）
- 对外方式二选一（详见 docs/deployment.md「对外暴露的两种场景」）：
  - **场景 A（推荐）**：HTTPS 反代指向 `127.0.0.1:8021`，`.env.deploy` 设 `COOKIE_SECURE=true`、`ALLOW_LOCAL_HTTP=false`
  - **场景 B（当前过渡，接管老端口 8001）**：`.env.deploy` 设 `API_BIND=0.0.0.0`、`API_PORT=8001`、`COOKIE_SECURE=false`、`ALLOW_LOCAL_HTTP=true`——**`COOKIE_SECURE` 必须为 false，否则 HTTP 下登录 Cookie 被浏览器拒绝、登录静默失效**

## 5. 回滚（任一环节失败时）

```bash
docker compose --env-file .env.deploy down     # 停新栈（数据卷保留）
sudo systemctl enable --now ai-marketing-tool  # 拉起旧服务
cp -a ~/backup-data-YYYY-MM-DD/. /path/to/repo/backend/data/   # 如旧库被触碰
```

旧服务确认稳定运行 ≥ 48 小时后，再考虑删除旧 venv 与备份数据（先归档）。
