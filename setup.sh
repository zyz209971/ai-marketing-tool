#!/usr/bin/env bash
# =============================================================================
# AI 营销素材生成工具 · 一键初始化脚本
# 用法：bash setup.sh
# 作用：装依赖 → 准备 .env（只需填一个千问 key）→ 重建 RAG 索引 → 提示启动
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/backend"

echo "==> [1/4] 创建虚拟环境并安装依赖"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
echo "    依赖已就绪"

echo "==> [2/4] 准备 .env（只需填一个千问 Key，文案/生图/解析/Embedding 全自动沿用）"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    已生成 backend/.env（模板）"
fi

# 如果 .env 里还没填 key，引导用户填写。
if ! grep -qE '^(QWEN_API_KEY|WORD_API_KEY)=[^[:space:]]+' .env 2>/dev/null; then
  echo ""
  echo "    ┌─────────────────────────────────────────────────────────┐"
  echo "    │  请打开 backend/.env，把下面这一行补上你的千问 Key：    │"
  echo "    │  WORD_API_KEY=sk-xxxx  （或 QWEN_API_KEY=sk-xxxx）        │"
  echo "    │  同一个 key 即可用于：文案 / 生图 / 反向解析 / Embedding │"
  echo "    └─────────────────────────────────────────────────────────┘"
  echo "    填好后重新运行：bash setup.sh"
  exit 0
fi

echo "==> [3/4] 重建 RAG 索引（数据源在 backend/data/ 下，随仓库一起提交）"
python scripts/update_marketing.py

echo "==> [4/4] 完成！启动后端："
echo "    source backend/.venv/bin/activate && cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000"
echo "    然后浏览器打开 http://127.0.0.1:8000 （访问密码见 .env 的 APP_ACCESS_KEY）"
