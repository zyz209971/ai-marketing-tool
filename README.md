# AI 营销素材生成工具

面向电商运营 / 校园奶茶商家的一键营销素材生成工具：上传产品信息 + 参考海报，自动生成新海报与多平台营销文案。

## 技术架构
- **前端**：`frontend/index.html` 单页应用（由后端静态托管）
- **后端**：`backend/` FastAPI 服务，串起主链路
- **主链路**：反向解析参考海报 → 结构化提示词替换 → 生图 → 生成营销文案

## 快速开始

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入 API key
uvicorn app.main:app --reload
```

浏览器打开 `http://127.0.0.1:8000` 即可使用。

## 运行模式
| 模式 | 触发条件 | 效果 |
|---|---|---|
| 演示模式（mock） | 未配置 `DASHSCOPE_API_KEY` | 出占位图 + 示例文案，可跑通全链路 |
| 真实模式 | 已配置 API key | 出真实生图 + 真实文案 |

## 环境变量（backend/.env）
- `DASHSCOPE_API_KEY`：阿里云百炼平台申请，用于生图（通义万相）+ 反向解析（千问-VL）
- `QWEN_LLM_API_KEY`：文案生成用（可复用上面的 key）
- `USE_MOCK=true`：强制 mock（界面演示用）

## 部署
本项目可通过平台「发布为应用」一键托管为在线链接（单端口 HTTP 服务）。上线前请在 `.env` 配置好 API key。

## 后续规划
- 二期：文生视频 / 首尾帧视频（即梦、可灵）
- 二期：知识库（商家产品库 / 爆款文案库 / 提示词模板库）
- 二期：联网搜索爆款文案接入
- 二期：自部署 SDXL/Flux + ComfyUI 降本
