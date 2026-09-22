#!/usr/bin/env bash
# CVPlatform 一键引导部署（面向全新机器：先探测环境，再选择可行路径）
#
# 用法（在服务器上，先解包发布包）：
#   cd ~ && tar -xzf /tmp/cvplatform-release-1.0.0.tar.gz
#   bash ~/cvplatform-release-1.0.0/deploy/user/bootstrap.sh ~/cvplatform-release-1.0.0 --port 80
#
# 它会依次处理三件事：
#   1) 环境探测：系统、Python 版本、是否可用 sudo/systemd、端口是否被占用；
#   2) Python 缺失时按可用权限安装（有 sudo 用 apt，没有则给出替代方案）；
#   3) **特权端口（<1024，例如 80）的绑定授权**——这是全新机器上最容易卡住的一步：
#        - 有 systemd 且可用 sudo：生成 systemd 单元，User=<当前用户> +
#          AmbientCapabilities=CAP_NET_BIND_SERVICE，由 systemd 授权绑 80；
#        - 无 systemd 但有 sudo：用 setcap 给虚拟环境的 python 加 cap_net_bind_service，
#          之后普通用户身份即可绑定 80；
#        - 都没有：无法绑定 80，自动退回高位端口（默认 8000）并打印 SSH 端口转发方式。
#
# 幂等：可重复执行；已存在的数据库不会被覆盖。

set -euo pipefail

# 自愈：CRLF 行尾会让 bash 报 $'\r': command not found
if [ -f "$0" ] && LC_ALL=C grep -q $'\r' "$0" 2>/dev/null; then
  LF_TMP="$(mktemp)"
  tr -d '\r' < "$0" > "$LF_TMP"
  exec bash "$LF_TMP" "$@"
fi

PORT=80
FALLBACK_PORT=8000
RELEASE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:-80}"; shift 2 ;;
    -*) echo "未知参数：$1" >&2; exit 2 ;;
    *) RELEASE_DIR="$1"; shift ;;
  esac
done

APP_DIR="${CVPLATFORM_APP_DIR:-$HOME/cvplatform}"
DATA_DIR="${CVPLATFORM_DATA_DIR:-$HOME/cvplatform-data}"
SERVICE_NAME=cvplatform
USER_NAME="$(id -un)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

log()  { printf '\n=== %s ===\n' "$*"; }
note() { printf '  %s\n' "$*"; }
fail() { echo "!! $*" >&2; exit 1; }

[[ -n "$RELEASE_DIR" && -d "$RELEASE_DIR/backend/app" ]] || fail "请给出发布包解压目录，例如 bash deploy/user/bootstrap.sh ~/cvplatform-release-1.0.0 --port 80"

log "0/5 环境探测"
note "系统：$(uname -srm)"
note "用户：$USER_NAME（家目录 $HOME）"
HAS_SUDO=0
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  HAS_SUDO=1
  note "sudo：可用（免密）"
elif command -v sudo >/dev/null 2>&1; then
  note "sudo：存在但需要密码——脚本内不会交互，特权步骤会给出你手动执行的命令"
else
  note "sudo：不存在"
fi
HAS_SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
  HAS_SYSTEMD=1
  note "systemd：可用"
else
  note "systemd：不可用"
fi
if (command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT ") ; then
  note "端口 $PORT：已被占用"
  PORT_IN_USE=1
else
  note "端口 $PORT：看起来可用"
  PORT_IN_USE=0
fi
[[ $PORT_IN_USE -eq 1 ]] && fail "端口 $PORT 已被占用，请先停掉占用进程或换端口（--port 其他值）"

log "1/5 Python 环境"
PY=""
for candidate in python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$(command -v "$candidate")"; break; fi
done

if [[ -z "$PY" ]]; then
  note "未找到 Python 3"
  if [[ $HAS_SUDO -eq 1 ]]; then
    note "用 sudo 安装 python3 / python3-venv / python3-pip …"
    sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv python3-pip
    PY="$(command -v python3)"
  else
    cat >&2 <<'EOF'
!! 机器上没有 Python 3，且当前用户没有可用的 sudo。
   请任选一种方式后重跑本脚本：
     a) 找管理员执行： sudo apt-get install -y python3 python3-venv python3-pip
     b) 用 conda/miniconda 自建环境，然后指定解释器：
        CVPLATFORM_PYTHON=$HOME/miniconda3/bin/python bash deploy/user/bootstrap.sh <发布目录> --port 80
     c) 该机器为 Ubuntu 24.04 时通常自带 python3.12，可先确认： ls /usr/bin/python3*
EOF
    exit 1
  fi
elif [[ -n "${CVPLATFORM_PYTHON:-}" ]]; then
  PY="$CVPLATFORM_PYTHON"
fi
note "使用解释器：$PY（$("$PY" -V 2>&1)）"
"$PY" - <<'PYEOF' || fail "Python 版本过低：需要 3.11+（项目使用 datetime.UTC 等特性）"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PYEOF
if ! "$PY" -m venv --help >/dev/null 2>&1; then
  if [[ $HAS_SUDO -eq 1 ]]; then
    note "virtualenv 模块不可用，用 sudo 安装 python3-venv …"
    sudo apt-get install -y -qq python3-venv
  else
    fail "Python 缺少 venv 模块，请让管理员安装 python3-venv（或改用 conda 环境）"
  fi
fi

log "2/5 部署应用（代码、前端、数据库、依赖）"
bash "$SCRIPT_DIR/install.sh" "$RELEASE_DIR" --port "${PORT_FOR_INSTALL:-$PORT}"
note "已按端口 $PORT 完成部署与首次启动自检"

log "3/5 端口 $PORT 的绑定授权"
BIND_OK=1
if [[ $PORT -lt 1024 ]]; then
  if [[ $EUID -eq 0 ]]; then
    note "当前是 root，可直接绑定"
  elif [[ $HAS_SYSTEMD -eq 1 && $HAS_SUDO -eq 1 ]]; then
    note "生成 systemd 单元并授予 CAP_NET_BIND_SERVICE（推荐）"
    UNIT=/etc/systemd/system/$SERVICE_NAME.service
    sudo bash -c "cat > '$UNIT'" <<EOF
[Unit]
Description=CVPlatform (FastAPI + Uvicorn, frontend served by backend)
After=network.target

[Service]
Type=simple
User=$USER_NAME
Group=$(id -gn)
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/env.sh
# 关键：允许非 root 用户绑定 80 这类特权端口
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn app.main:app --app-dir $APP_DIR/backend --host 0.0.0.0 --port $PORT --workers 1
Restart=always
RestartSec=3
MemoryMax=800M
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now $SERVICE_NAME
    note "已启动 $SERVICE_NAME（systemd 负责绑定 $PORT 并自动重启）"
    note "此路径下请用 systemctl 管理：systemctl status|restart|stop $SERVICE_NAME"
  elif command -v sudo >/dev/null 2>&1 && command -v setcap >/dev/null 2>&1; then
    note "无免密 sudo：请手动执行下面这一条，给虚拟环境的解释器授予绑定特权端口的能力"
    echo
    echo "    sudo setcap 'cap_net_bind_service=+ep' $APP_DIR/.venv/bin/python3*"
    echo
    note "执行后重跑： bash $SCRIPT_DIR/ctl.sh restart"
  else
    BIND_OK=0
  fi
fi

log "4/5 启动方式确认"
if [[ $PORT -lt 1024 && $EUID -ne 0 && ! ( $HAS_SYSTEMD -eq 1 && $HAS_SUDO -eq 1 ) ]]; then
  note "当前权限下无法绑定 $PORT。可选方案："
  note "  a) 执行上面的 setcap 命令（需要管理员协助一次）后重启；"
  note "  b) 退回高位端口并使用 SSH 端口转发："
  echo
  echo "     bash $APP_DIR/deploy/user/ctl.sh stop"
  echo "     bash $SCRIPT_DIR/install.sh $RELEASE_DIR --port $FALLBACK_PORT"
  echo "     ssh -L 8080:127.0.0.1:$FALLBACK_PORT $USER_NAME@$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "     # 然后本地浏览器打开 http://127.0.0.1:8080"
  echo
  BIND_OK=0
elif [[ $HAS_SYSTEMD -eq 1 && $HAS_SUDO -eq 1 && $PORT -lt 1024 ]]; then
  note "由 systemd 托管；健康检查："
  curl -s -o /dev/null -w "    http://127.0.0.1:$PORT/api/health → %{http_code}\n" "http://127.0.0.1:$PORT/api/health" || true
else
  note "由 deploy/user/ctl.sh 托管（nohup + PID 文件）；健康检查："
  curl -s -o /dev/null -w "    http://127.0.0.1:$PORT/api/health → %{http_code}\n" "http://127.0.0.1:$PORT/api/health" || true
fi

log "5/5 结果"
if [[ $BIND_OK -eq 1 ]]; then
  note "站点已在端口 $PORT 提供服务（页面与接口同一进程）。"
  note "公网访问需要在安全组/防火墙放行 $PORT。"
  curl -s "http://127.0.0.1:$PORT/api/stats/coverage" | head -c 240; echo
else
  note "尚未在本机绑定 $PORT：按上面的方案 a 或 b 处理后即可访问。"
fi
