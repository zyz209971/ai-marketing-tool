# 上线检查清单（每次部署到生产前逐条勾选）

生产环境模型为**百炼**。逐项打勾后再执行切换；任何一项不过即中止并回滚。

## A. 代码与门禁

- [ ] 变更已通过 PR 合并进 `main`（不部署任何非 main 分支）
- [ ] CI 全绿（Python 编译检查、前端测试、敏感文件门禁）
- [ ] `python -m pytest backend/tests` 全过
- [ ] `node --test frontend/tests/*.test.mjs` 全过
- [ ] `python backend/scripts/check_repo_safety.py` 无告警
- [ ] RELEASE_MANIFEST 与树一致（`python scripts/make_release_manifest.py --check`）

## B. 配置（.env.deploy，只在服务器，不进 Git）

- [ ] `DB_PASSWORD` 为强随机值
- [ ] `AGENT_API_KEY / AGENT_BASE_URL / AGENT_MODEL`、`WORD_API_KEY / COPY_MODEL`、`EMBED_API_KEY / EMBED_BASE_URL / EMBED_MODEL` 全部指向**百炼**且三者同源（URL/Key/模型配套）
- [ ] 代码与 example 中不含任何真实端点/密钥（本地 OpenRouter 等配置不得带入）
- [ ] `USE_MOCK=false`、`SEED_DEMO_DATA=false`
- [ ] 对外服务时：`COOKIE_SECURE=true`、`ALLOW_LOCAL_HTTP=false`、HTTPS 反代就绪（保留 Host 头）

## C. 数据与索引

- [ ] 旧部署已备份（SQLite 库 + 旧 `.env`，按 docs/deploy-cutover.md）
- [ ] 产品知识库导入：`python scripts/import_csv.py ../产品知识库.csv`
- [ ] 营销案例导入并**以百炼 embedding 重建索引**：`python scripts/update_marketing.py ../marketing`
  （换 embedding 模型后旧向量会被自动忽略、降级为词法检索——必须重建才能恢复语义检索）
- [ ] RAG 抽查：搜索 2–3 条真实问题，确认语义结果非空且相关

## D. 部署与验证

- [ ] `docker compose --env-file .env.deploy up --build -d` 成功，容器 healthy
- [ ] 数据库与 /data 卷已纳入备份并演练过恢复
- [ ] 建号：`manage_account.py`，密码交互输入
- [ ] 冒烟（真实模型）：登录 → 建品牌 → 生成一条文案 → 一张图 → 多轮追问一次
- [ ] 工作区隔离抽查：A 工作区看不到 B 的品牌/任务
- [ ] 重启恢复演练：`docker compose restart` 后任务与登录态正常
- [ ] 回滚路径确认：旧 systemd 服务可一键拉起（见 deploy-cutover.md）

## E. 遗留豁免（当前已知、上线时接受的限制）

- 单 API 进程（禁止多副本）；Embedding 未配置时词法降级属预期
