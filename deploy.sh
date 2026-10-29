#!/usr/bin/env bash
# AI 营销素材生成工具 · 一键部署脚本（腾讯云 Ubuntu 22.04）
#
# 用法：在服务器上，项目根目录下执行
#   bash deploy.sh
#
# 这个脚本会：
#   1. 安装 Python3、pip、venv
#   2. 创建虚拟环境并安装依赖
#   3. 根据 .env 生成启动所需的 systemd 服务（开机自启 + 崩溃自动重启）
#   4. 启动服务
#
set -e

echo "==> 1/5 更新系统并安装 Python 依赖"
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv

cd "$(dirname "$0")"

echo "==> 2/5 创建虚拟环境并安装依赖"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "==> 3/5 检查 .env 配置"
if [ ! -f "backend/.env" ]; then
  echo "   未找到 backend/.env，请先复制 .env.example 并填入 API key。"
  echo "   参考命令：cp backend/.env.example backend/.env"
  exit 1
fi

echo "==> 4/5 配置 systemd 服务（开机自启）"
SERVICE_FILE="/etc/systemd/system/ai-marketing-tool.service"
APP_DIR="$(pwd)"
sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=AI Marketing Tool (FastAPI)
After=network.target

[Service]
WorkingDirectory=$APP_DIR/backend
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
EnvironmentFile=$APP_DIR/backend/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ai-marketing-tool

echo "==> 5/5 启动服务"
sudo systemctl restart ai-marketing-tool

echo ""
echo "✅ 部署完成！"
echo "   访问地址: http://<服务器公网IP>:8000"
echo "   查看状态: sudo systemctl status ai-marketing-tool"
echo "   查看日志: sudo journalctl -u ai-marketing-tool -f"
echo ""
echo "⚠️  如果访问不了，请去腾讯云控制台的「防火墙」里放行 8000 端口。"
