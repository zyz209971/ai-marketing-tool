## 改动说明

<!-- 一句话说清这个 PR 做了什么；涉及界面改动请附截图 -->

## 改动范围

- [ ] 代码（backend / frontend）
- [ ] 产品知识库（`产品知识库.csv`，改后需跑 `python scripts/import_csv.py ../产品知识库.csv`）
- [ ] 营销案例（`marketing/`，改后需跑 `python scripts/update_marketing.py ../marketing`）
- [ ] 文档

## 自测清单

- [ ] 本地启动正常（后端无报错，页面可打开）
- [ ] `node --test frontend/tests/` 通过
- [ ] 改了数据源文件的话，已重新导入并在页面确认生效
- [ ] 没有提交 `.env*`、`*.db`、密钥或本地产物（CI 门禁会拦）

## 部署提示（合并后需要做什么）

<!-- 例如：需要重建 RAG 索引 / 需要新环境变量 / 无需额外操作 -->
