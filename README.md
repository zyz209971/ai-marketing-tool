# AI 营销素材生成工具

品牌知识库本地开发、配置和使用说明见 [品牌知识库-本地开发说明](品牌知识库-本地开发说明.md)。

当前功能分支提供单个共享品牌工作空间，无注册、登录、短信或成员权限。品牌可搜索并补充知识，产品库支持筛选分页，营销创作通过选择器添加产品；支持资料确认入库、草稿、任务记录、实拍排版及素材导出。默认仅允许本机直接访问，此版本尚未完成真实模型与公网部署验收。

面向电商运营 / 校园奶茶商家的一键营销素材生成工具：上传产品信息 + 参考海报，自动生成新海报与多平台营销文案（小红书 / 抖音 / 公众号）。

2026-11-03 合并：默认入口已采用 frontend-v2 的品牌工作空间界面，并接入现有后端和 RAG。
清理后仅保留合并版页面。文件改动、原因和自行测试步骤见 [前端合并改动说明](前端合并改动说明-2026-11-03.md)。

2026-11-04：将已修改的前端、RAG 和评测资产迁入原仓库的功能分支，保留原提交历史。
迁移范围、首次初始化及提交命令见 [迁移与提交说明](迁移与提交说明-2026-11-04.md)。

---

## ⚡ 一句话操作速查（团队同学看这里）

- **改产品（价格/卖点）**：在产品库搜索产品 → 编辑并保存；参考目录的历史价格需核对
- **重建 RAG（标准数据）**：在 `backend/` 跑 `python scripts/update_marketing.py`
- **补充品牌资料**：品牌知识页 → 补充资料 → 核对并确认
- **只加新案例不清旧**：上面命令末尾加 `--append`
- **改代码**：创建功能分支 → 修改并检查差异 → 提交并推送该分支 → 创建 PR 审核合并

> 详细步骤见《团队协作与知识库更新说明.md》。

---

## 技术架构

- **前端**：`frontend/index.html` + 原生 JavaScript 模块和 CSS（由后端直接托管，无需前端构建）
- **后端**：`backend/` FastAPI 服务
- **主链路**：品牌与产品事实 + 营销目的 → 按平台生成文案 → 按需解析参考海报并生图 → 文案改写 / 多轮改图 / 本地保存
- **知识库**：SQLite 产品库 + 中文 FTS5/n-gram 混合 RAG；配置独立 Embedding API 后自动叠加语义检索

## 快速开始

需要 Python 3.10+；下面使用 Mac 上已有的 Python 3.11。命令从仓库根目录开始执行，
已有可用环境时可直接使用对应解释器。

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# 已有 .env 请保留；仅首次使用、且没有该文件时创建
if [ ! -f .env ]; then cp .env.example .env; fi
# 仅新克隆且没有 data/marketing.db 时初始化；已有索引不必重建
if [ ! -f data/marketing.db ]; then python scripts/update_marketing.py; fi
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers
```

首次启动的品牌工作空间为空，不会自动植入示例产品。若要使用仓库已有资料建立与本地预览一致的品牌目录，可在安装依赖后、从 `backend/` 执行：

```bash
# 只初始化数据结构，不启动服务器；已有环境先备份。
python -c "from app.main import app; from app import rag; rag.init_db()"
python scripts/prepare_production_data.py --output ../.local-data/production-data-001
python scripts/prepare_local_workspace.py --source ../.local-data/production-data-001/production --runtime ../.local-data/workspace-001 --backup ../.local-data/before-import-001
python scripts/run_local_preview.py --runtime ../.local-data/workspace-001 --port 8018
```

以上目录必须是尚未使用的新目录，脚本拒绝覆盖已有内容。可给第二条准备工作空间的命令增加 `--fetch-images`，从原记录的品牌 CDN 下载产品图；缺图时可手动上传。备份、数据库、图片与生成物均不进入 Git。`.env` 中与 `APP_DATA_DIR`、`BRAND_DATABASE_URL`、`BRAND_STORAGE_DIR` 冲突的值需要先移除；本地启动器会拒绝使用错误的数据目录。

浏览器打开 `http://127.0.0.1:8000` 即可使用。
此仓库保留原始 JSONL，但不提交本机 `.env` 和 SQLite 数据库；新克隆需要按上述步骤初始化索引。
没有 Embedding Key 时可先建立本地关键词索引；需要向量检索时由你配置后另行构建。
已有环境和索引时只需重启后端并强制刷新网页。前端不需要填写模型密钥。

## 运行模式

| 模式 | 触发条件 | 效果 |
|---|---|---|
| 文字演示 | 未配置文字 Key，或强制 mock | 返回模板文案 |
| 图片演示 | 未配置图片 Key，或强制 mock | 返回明确标注的占位图 |
| 本地检索 | 未配置 Embedding Key 或模型 | 使用 FTS5 / n-gram 与元数据评分 |
| 对应真实服务 | 对应 Key 与模型配置有效 | 使用已配置的文字、图片或 Embedding 服务 |

## 环境变量（backend/.env）

- `WORD_API_KEY`（兼容 `QWEN_API_KEY`）：文字与视觉服务密钥
- `IMAGE_API_KEY` / `IMAGE_BASE_URL`：独立生图配置
- `EMBED_API_KEY` / `EMBED_BASE_URL`：独立 Embedding 配置，未配置时保留本地关键词检索
- `QWEN_BASE_URL`：OpenAI 兼容协议端点地址
- `IMAGE_MODEL` / `VISION_MODEL` / `COPY_MODEL` / `EMBED_MODEL`：各环节所用模型

## 主要接口

新版页面使用 `/api/v2/copywriting`、`/api/v2/images`、`/api/v2/images/revise`、
`/api/v2/copywriting/rewrite`、`/api/v2/products/search`；详见 [新版接口说明](frontend/docs/API.md)。
以下旧接口继续保留：

- `POST /api/generate` — 图文一起生成
- `POST /api/copywriting` — 只生成文案
- `POST /api/image` — 只生成图片
- `POST /api/revise` — 多轮改图
- `GET /api/search` — 产品联想补全
- `GET /api/rag_search` — 营销案例语义检索
- `GET /api/rag_stats` — 查看 RAG 索引规模与检索模式

## RAG 数据更新

`backend/data/产品.jsonl`、`推文.jsonl`、`小红书推文.jsonl` 是默认数据源。以下命令用于明确需要全量重建时，
会替换当前索引；查看或评测已有索引不需要先重建：

```bash
cd backend
python3.11 scripts/update_marketing.py
```

系统会保留产品、平台、品牌、来源层级等元数据，自动去重并建立中文全文索引。
当前文字 API 没有 Embedding 能力时仍可检索；如需语义向量检索，在 `.env` 额外配置
`EMBED_BASE_URL`、`EMBED_API_KEY`、`EMBED_MODEL` 后重新建库即可。

## 部署

本项目可通过平台「发布为应用」一键托管为在线链接（单端口 HTTP 服务）。上线前请在 `.env` 配置好 API key。

## 后续规划

- 二期：文生视频 / 首尾帧视频
- 二期：联网搜索爆款文案接入
- 二期：知识库网页管理界面
- 二期：自部署 SDXL/Flux + ComfyUI 降本
