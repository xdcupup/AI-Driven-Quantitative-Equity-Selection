#!/bin/bash
# =============================================================================
# AI 量化数据流水线 — 每日定时运行脚本
# =============================================================================
# 此脚本由 Hermes cron 每日调用
# 执行时间：每个交易日收盘后（建议 16:00 后）
# 
# 前置条件:
#   - Python 3.11+ venv 已创建
#   - 依赖已安装 (pip install -r requirements.txt)
#   - 网络可访问 mootdx / 腾讯 / 百度直连数据源
# =============================================================================

set -euo pipefail

# --- 配置 ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PATH="$PROJECT_DIR/.venv"
PIPELINE_SCRIPT="$PROJECT_DIR/pipeline.py"
LOG_DIR="$PROJECT_DIR/logs"
DATE=$(date +%Y-%m-%d)

# --- 日志 ---
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron_${DATE}.log"

exec 1>>"$LOG_FILE" 2>&1

echo "========================================"
echo "🕐 Cron 启动: $(date)"
echo "  项目: $PROJECT_DIR"
echo "========================================"

# --- 切换到项目目录 ---
cd "$PROJECT_DIR"

# --- 激活虚拟环境 ---
if [ ! -d "$VENV_PATH" ]; then
    echo "❌ 虚拟环境不存在: $VENV_PATH"
    echo "   请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source "$VENV_PATH/bin/activate"

# --- 检查依赖 ---
python3 -c "import mootdx" 2>/dev/null || {
    echo "❌ mootdx 未安装，尝试安装依赖..."
    pip install -r "$PROJECT_DIR/requirements.txt" 2>&1
}

# --- 设置环境变量（绕过系统代理） ---
export all_proxy=""

# --- 运行流水线 ---
echo ""
echo "🚀 运行数据流水线..."
set +e
python3 "$PIPELINE_SCRIPT" --date "$DATE" 2>&1
EXIT_CODE=$?
set -e

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 流水线执行成功 (exit=$EXIT_CODE)"
else
    echo "⚠️  流水线执行异常 (exit=$EXIT_CODE)"
fi

# --- 数据库大小 ---
DB_PATH="$PROJECT_DIR/data/quant.duckdb"
if [ -f "$DB_PATH" ]; then
    SIZE=$(du -h "$DB_PATH" | cut -f1)
    echo "📦 数据库大小: $SIZE"
fi

echo ""
echo "📋 日志文件: $LOG_FILE"
echo "========================================"
echo "🏁 Cron 完成: $(date)"
echo "========================================"

exit $EXIT_CODE
