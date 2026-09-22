#!/usr/bin/env bash
# CVPlatform 进程控制（用户级：nohup + PID 文件，不依赖 systemd）
#
# 用法：
#   bash ~/cvplatform/deploy/user/ctl.sh start|stop|restart|status|logs
#
# 说明：
# - 环境变量从 ~/cvplatform/env.sh 读取（由 install.sh 生成）；
# - 日志写到 ~/cvplatform/logs/app.log，按 5MB 轮转一次（保留 app.log.1）；
# - 单 worker：SQLite 写入与后台任务都按单进程设计，不要开多个实例。

set -euo pipefail

# 自愈：CRLF 行尾会让 bash 报 $'\r': command not found
if [ -f "$0" ] && LC_ALL=C grep -q $'\r' "$0" 2>/dev/null; then
  LF_TMP="$(mktemp)"
  tr -d '\r' < "$0" > "$LF_TMP"
  exec bash "$LF_TMP" "$@"
fi

APP_DIR="${CVPLATFORM_APP_DIR:-$HOME/cvplatform}"
ENV_FILE="$APP_DIR/env.sh"
PID_FILE="$APP_DIR/cvplatform.pid"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/app.log"
SERVICE_NAME="${CVPLATFORM_SERVICE:-cvplatform}"
UNIT_FILE="/etc/systemd/system/$SERVICE_NAME.service"

[[ -f "$ENV_FILE" ]] || { echo "缺少 $ENV_FILE，请先执行 deploy/user/install.sh" >&2; exit 1; }

# env.sh 是纯 KEY=value（systemd 的 EnvironmentFile 也读它，所以不能写 export），
# 用 set -a 临时打开自动导出，保证子进程能拿到这些变量
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
PORT="${CVPLATFORM_PORT:-8000}"
VENV_PY="$APP_DIR/.venv/bin/python"

# 同一个应用只允许一种启动方式：systemd 已经在管的时候再用 nohup 启动会抢同一个端口
systemd_managed() {
  [[ -f "$UNIT_FILE" ]] && command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

# systemd 托管时统一走这里；非 root 需要用 sudo（免密时无感，需要密码时会提示）
sysctl_do() {
  local action="$1" prefix=""
  shift
  [[ $EUID -ne 0 ]] && prefix="sudo"
  $prefix systemctl "$action" "$SERVICE_NAME" "$@"
}

running_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  echo "$pid"
}

start() {
  if systemd_managed; then
    echo "本应用由 systemd 单元 $SERVICE_NAME 托管，转给 systemctl（两套启动方式会抢同一个端口）"
    sysctl_do start
    return 0
  fi
  if pid="$(running_pid)"; then
    echo "已在运行（PID $pid，端口 $PORT）"
    return 0
  fi
  mkdir -p "$LOG_DIR"
  # 日志轮转：超过 5MB 就改名保留一份，避免长期运行把磁盘写满
  if [[ -f "$LOG_FILE" ]] && [[ $(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0) -gt 5242880 ]]; then
    mv -f "$LOG_FILE" "$LOG_FILE.1"
  fi
  cd "$APP_DIR"
  # 单 worker：后台任务与 SQLite 写入都按单进程设计
  nohup "$VENV_PY" -m uvicorn app.main:app \
    --app-dir "$APP_DIR/backend" \
    --host 127.0.0.1 --port "$PORT" --workers 1 \
    >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  echo "已启动（PID $(cat "$PID_FILE")，端口 $PORT，日志 $LOG_FILE）"
}

stop() {
  if systemd_managed; then
    echo "本应用由 systemd 单元 $SERVICE_NAME 托管，转给 systemctl"
    sysctl_do stop
    return 0
  fi
  if pid="$(running_pid)"; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    echo "已停止（PID $pid）"
  else
    echo "未在运行"
  fi
  rm -f "$PID_FILE"
}

status() {
  if systemd_managed; then
    sysctl_do status --no-pager -l | head -n 12 || true
    echo "健康检查：$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:$PORT/api/health")"
    return 0
  fi
  if pid="$(running_pid)"; then
    echo "运行中：PID $pid，端口 $PORT"
    echo "健康检查：$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:$PORT/api/health")"
    echo "内存占用：$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.0f MB\n", $1/1024}')"
  else
    echo "未运行（日志：$LOG_FILE）"
    return 1
  fi
}

logs() {
  tail -n "${2:-50}" "$LOG_FILE"
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) status ;;
  logs) logs "$@" ;;
  *) echo "用法：bash $0 start|stop|restart|status|logs [行数]" >&2; exit 2 ;;
esac
