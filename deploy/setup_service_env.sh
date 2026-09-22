#!/usr/bin/env bash
# 为 cvplatform.service 配置生产环境变量（幂等，可重复执行）
#
# 背景：服务器上原有的 cvplatform.service 没有设置 CVPLATFORM_ENV / CVPLATFORM_DB_PATH，
# 应用会退回「开发默认路径」<应用目录>/data/cvplatform.db；服务以 cvplatform 运行、
# 而应用目录属主是 root，于是启动时报
#   PermissionError: [Errno 13] Permission denied: '/opt/cvplatform/data'
#
# 做法：不改动你原有的单元文件，而是用 systemd 的 drop-in 追加两行；
#       环境变量值放进 /etc/cvplatform.env（模板 deploy/env.example，权限 0640、属主 root:cvplatform）。
#
# 用法：sudo bash deploy/setup_service_env.sh [应用目录] [数据目录]
#       默认 /opt/cvplatform 与 /var/lib/cvplatform

set -euo pipefail

# 自愈：CRLF 行尾会让 bash 报 $'\r': command not found
if [ -f "$0" ] && LC_ALL=C grep -q $'\r' "$0" 2>/dev/null; then
  LF_TMP="$(mktemp)"
  tr -d '\r' < "$0" > "$LF_TMP"
  exec bash "$LF_TMP" "$@"
fi

APP_DIR="${1:-/opt/cvplatform}"
DATA_DIR="${2:-/var/lib/cvplatform}"
SERVICE=cvplatform.service
ENV_FILE=/etc/cvplatform.env
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/10-cvplatform-env.conf"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "请用 sudo 执行" >&2; exit 1; }
id cvplatform >/dev/null || { echo "运行用户 cvplatform 不存在" >&2; exit 1; }

echo "== 1/4 数据目录 =="
install -d -o cvplatform -g cvplatform -m 0750 "$DATA_DIR" "$DATA_DIR/backups"
ls -ld "$DATA_DIR" | sed 's/^/  /'

echo "== 2/4 环境文件 $ENV_FILE =="
if [[ -f "$ENV_FILE" ]]; then
  echo "  已存在，保留现有内容（如需更新请自行编辑）"
  # 只补齐缺失的关键项，不覆盖人工修改
  grep -q '^CVPLATFORM_ENV=' "$ENV_FILE" || echo "CVPLATFORM_ENV=production" >> "$ENV_FILE"
  grep -q '^CVPLATFORM_DB_PATH=' "$ENV_FILE" || echo "CVPLATFORM_DB_PATH=$DATA_DIR/cvplatform.db" >> "$ENV_FILE"
else
  if [[ -f "$SCRIPT_DIR/env.example" ]]; then
    install -o root -g cvplatform -m 0640 "$SCRIPT_DIR/env.example" "$ENV_FILE"
  else
    printf 'CVPLATFORM_ENV=production\nCVPLATFORM_DB_PATH=%s/cvplatform.db\n' "$DATA_DIR" > "$ENV_FILE"
    chown root:cvplatform "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
  fi
  echo "  已创建（来自 env.example）"
fi
grep -E '^(CVPLATFORM_ENV|CVPLATFORM_DB_PATH)=' "$ENV_FILE" | sed 's/^/  /'

echo "== 3/4 systemd drop-in $DROPIN =="
install -d -m 0755 "$DROPIN_DIR"
cat > "$DROPIN" <<EOF
# 由 deploy/setup_service_env.sh 生成：让服务读取生产环境变量文件，
# 从而把数据库固定到 $DATA_DIR（而不是应用目录下的开发默认路径）。
[Service]
EnvironmentFile=-$ENV_FILE
Environment=PYTHONPATH=$APP_DIR/backend
EOF
echo "  已写入："
sed 's/^/    /' "$DROPIN"

echo "== 4/4 生效 =="
systemctl daemon-reload
echo "  已 daemon-reload；接着执行：sudo systemctl restart $SERVICE"
echo "  启动后自检：systemctl is-active $SERVICE && curl -s http://127.0.0.1:8000/api/stats/coverage | head -c 200"
