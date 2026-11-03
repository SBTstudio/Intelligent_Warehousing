#!/usr/bin/env bash
# 智能仓储管理系统 — macOS / Linux 启动脚本
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "============================================================"
  echo " [错误] 还没有创建虚拟环境 .venv"
  echo "        请先执行："
  echo "          python3.12 -m venv .venv"
  echo "          source .venv/bin/activate"
  echo "          pip install -r requirements.txt"
  echo "============================================================"
  exit 1
fi

exec .venv/bin/python main.py
