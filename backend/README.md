# AI 营销素材生成工具 · 后端

FastAPI 服务，串起「反向解析 → 提示词替换 → 生图 → 文案生成」主链路。

## 目录结构
```
backend/
  app/
    main.py           # FastAPI 入口，/api/generate 接口 + 静态托管前端
    config.py         # 环境变量配置（API keys）
    pipeline.py       # 生成主链路编排
    providers/
      __init__.py
      vision.py       # 反向解析（通义千问-VL / mock）
      image.py        # 生图（通义万相 / mock）
      copywriting.py  # 文案生成（国内大模型 / mock）
  requirements.txt
  .env.example
```

## 本地运行
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入你的 API key
uvicorn app.main:app --reload
```

## 环境变量（在 .env 中配置）
| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 通义万相(生图) + 千问-VL(解析) 共用，阿里云百炼平台申请 |
| `QWEN_LLM_API_KEY` | 文案生成用（可复用 DASHSCOPE 或单独 key） |
