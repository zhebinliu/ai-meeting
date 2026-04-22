#!/bin/bash
# ==============================================================================
# Meeting-AI 生产部署脚本
# 用法: ./deploy.sh [--no-migrate] [--no-restart]
# ==============================================================================
set -e

# --- 配置 ---
SERVER="liu@34.136.165.103"
SSH_KEY="$HOME/Downloads/gcp_key"
REMOTE_DIR="/home/liu/meeting-ai"
SERVICE_NAME="meeting-ai"
DB_PATH="$REMOTE_DIR/meeting_ai.db"

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SERVER"
RSYNC_CMD="rsync -avz -e 'ssh -i $SSH_KEY -o StrictHostKeyChecking=no'"

# --- 参数解析 ---
SKIP_MIGRATE=false
SKIP_RESTART=false
for arg in "$@"; do
  case $arg in
    --no-migrate) SKIP_MIGRATE=true ;;
    --no-restart) SKIP_RESTART=true ;;
  esac
done

echo "======================================================"
echo "  Meeting-AI 部署开始 $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================"

# --- 步骤 1: 同步代码 ---
echo ""
echo ">>> [1/4] 同步代码到服务器..."
rsync -avz \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  --exclude-from=".rsyncignore" \
  --delete \
  ./ $SERVER:$REMOTE_DIR/

echo "    ✓ 代码同步完成"

# --- 步骤 2: 数据库迁移 ---
if [ "$SKIP_MIGRATE" = false ]; then
  echo ""
  echo ">>> [2/4] 执行数据库迁移..."
  $SSH_CMD python3 - <<'PYEOF'
import sqlite3, os
db = '/home/liu/meeting-ai/meeting_ai.db'
if not os.path.exists(db):
    print("    数据库不存在，将由应用自动创建")
    exit(0)
conn = sqlite3.connect(db)
c = conn.cursor()
c.execute('PRAGMA table_info(meetings)')
cols = [r[1] for r in c.fetchall()]
migrations = {
    'total_chunks':       'INTEGER NOT NULL DEFAULT 0',
    'done_chunks':        'INTEGER NOT NULL DEFAULT 0',
    'asr_engine':         'VARCHAR(32)',
    'bitable_app_token':  'VARCHAR(128)',
    'feishu_url':         'TEXT',
    'created_at':         'DATETIME',
    'polished_transcript':'TEXT',
    'meeting_minutes':    'TEXT',
}
added = []
for col, typedef in migrations.items():
    if col not in cols:
        c.execute(f'ALTER TABLE meetings ADD COLUMN {col} {typedef}')
        added.append(col)
conn.commit()
conn.close()
if added:
    print(f"    ✓ 已添加字段: {', '.join(added)}")
else:
    print("    ✓ 数据库已是最新，无需迁移")
PYEOF
else
  echo ">>> [2/4] 跳过数据库迁移 (--no-migrate)"
fi

# --- 步骤 3: 重启服务 ---
if [ "$SKIP_RESTART" = false ]; then
  echo ""
  echo ">>> [3/4] 重启服务..."
  $SSH_CMD sudo systemctl restart $SERVICE_NAME
  sleep 3
  echo "    ✓ 服务已重启"
else
  echo ">>> [3/4] 跳过服务重启 (--no-restart)"
fi

# --- 步骤 4: 验证 ---
echo ""
echo ">>> [4/4] 验证服务状态..."
STATUS=$($SSH_CMD sudo systemctl is-active $SERVICE_NAME 2>/dev/null || echo "unknown")
if [ "$STATUS" = "active" ]; then
  echo "    ✓ 服务状态: $STATUS"
else
  echo "    ✗ 服务状态异常: $STATUS，查看最近日志:"
  $SSH_CMD sudo journalctl -u $SERVICE_NAME -n 20 --no-pager
  exit 1
fi

# 检查日志中是否有 startup complete
STARTUP=$($SSH_CMD sudo journalctl -u $SERVICE_NAME -n 10 --no-pager 2>/dev/null | grep "startup complete" || echo "")
if [ -n "$STARTUP" ]; then
  echo "    ✓ 应用已成功启动"
else
  echo "    ⚠ 未检测到 startup complete，查看日志确认状态"
  $SSH_CMD sudo journalctl -u $SERVICE_NAME -n 20 --no-pager
fi

echo ""
echo "======================================================"
echo "  部署完成 ✓  $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================"
