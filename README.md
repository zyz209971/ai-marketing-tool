# AI 营销素材生成工具

面向电商运营 / 校园奶茶商家的一键营销素材生成工具：上传产品信息 + 参考海报，自动生成新海报与多平台营销文案（小红书 / 抖音 / 公众号）。

---

## ⚡ 一句话操作速查（团队同学看这里）

- **改产品（价格/卖点）**：改 `产品知识库.csv` → 跑 `python scripts/import_csv.py ../产品知识库.csv`
- **改 RAG（营销案例）**：案例丢进 `marketing/` → 跑 `python scripts/update_marketing.py ../marketing`
- **只加新案例不清旧**：上面命令末尾加 `--append`
- **改代码**：`git pull` → 改文件 → `git push`

> 详细步骤见《团队协作与知识库更新说明.md》。

---

## 技术架构

- **前端**：`frontend/index.html` 单页应用（由后端静态托管）
- **后端**：`backend/` FastAPI 服务
- **主链路**：反向解析参考海报 → 结构化提示词替换 → 生图 → 生成营销文案
- **知识库**：SQLite 产品库（产品名 → 价格+卖点）+ RAG 营销案例向量库（语义检索）

## 快速开始

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填入自己的 API key
uvicorn app.main:app --reload
```

浏览器打开 `http://127.0.0.1:8000` 即可使用。

## 运行模式

| 模式 | 触发条件 | 效果 |
|---|---|---|
| 演示模式（mock） | 未配置 API key | 出占位图 + 示例文案，可跑通全链路 |
| 真实模式 | 已配置 API key | 出真实生图 + 真实文案 |

## 环境变量（backend/.env）

- `QWEN_API_KEY`：阿里云百炼 MaaS 平台的 API key（生图 / 文案 / 反向解析 / embedding 共用）
- `QWEN_BASE_URL`：OpenAI 兼容协议端点地址
- `IMAGE_MODEL` / `VISION_MODEL` / `COPY_MODEL` / `EMBED_MODEL`：各环节所用模型

## 主要接口

- `POST /api/generate` — 图文一起生成
- `POST /api/copywriting` — 只生成文案
- `POST /api/image` — 只生成图片
- `POST /api/revise` — 多轮改图
- `GET /api/search` — 产品联想补全
- `GET /api/rag_search` — 营销案例语义检索

## 部署

本项目可通过平台「发布为应用」一键托管为在线链接（单端口 HTTP 服务）。上线前请在 `.env` 配置好 API key。

## 后续规划

- 二期：文生视频 / 首尾帧视频
- 二期：联网搜索爆款文案接入
- 二期：知识库网页管理界面
- 二期：自部署 SDXL/Flux + ComfyUI 降本
