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
# 项目需要 3.11+（使用 datetime.UTC；已核对全仓仅此一处 3.11+ 特性）。
# 很多云主机（例如 Ubuntu 22.04）自带的是 3.10，因此这里**实测版本**而不是只看命令是否存在，
# 并按“机器已有 → 发行版仓库 → deadsnakes PPA → 用户态独立解释器”的顺序补齐。
VER_CHECK='import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
PY=""

py_ok() { [[ -n "${1:-}" ]] && [[ -x "$1" ]] && "$1" -c "$VER_CHECK" >/dev/null 2>&1; }

pick_py() {
  local cand p
  for cand in python3.13 python3.12 python3.11 python3 python; do
    p="$(command -v "$cand" 2>/dev/null || true)"
    if py_ok "$p"; then PY="$p"; return 0; fi
  done
  return 1
}

# Ubuntu 24.04 等自带仓库里就有 3.12
install_py312_apt() {
  apt-cache policy python3.12 2>/dev/null | grep -q 'Candidate: [0-9]' || return 1
  note "发行版仓库提供 python3.12，直接安装"
  sudo apt-get update -qq && sudo apt-get install -y -qq python3.12 python3.12-venv
}

# Ubuntu 22.04（jammy）等自带仓库只有 3.10，3.12 走 deadsnakes
install_py312_deadsnakes() {
  note "自带仓库没有 3.12，添加 deadsnakes PPA 安装 python3.12"
  sudo apt-get update -qq || return 1
  sudo apt-get install -y -qq software-properties-common || return 1
  sudo add-apt-repository -y ppa:deadsnakes/ppa || return 1
  sudo apt-get update -qq || return 1
  sudo apt-get install -y -qq python3.12 python3.12-venv
}

# 无 sudo 或上面都失败时的兜底：uv 下载官方独立 CPython（用户态，不碰系统）
install_py312_uv() {
  command -v curl >/dev/null 2>&1 || return 1
  note "改用 uv 安装独立 CPython 3.12（用户态 $HOME/.local，不需要 sudo）"
  curl -LsSf https://astral.sh/uv/install.sh | sh || return 1
  local uv="$HOME/.local/bin/uv"
  [[ -x "$uv" ]] || uv="$(command -v uv 2>/dev/null || true)"
  [[ -n "$uv" ]] || return 1
  "$uv" python install 3.12 || return 1
  PY="$("$uv" python find 3.12 2>/dev/null || true)"
  py_ok "$PY"
}

if [[ -n "${CVPLATFORM_PYTHON:-}" ]]; then
  PY="$CVPLATFORM_PYTHON"
  py_ok "$PY" || fail "CVPLATFORM_PYTHON 指向的解释器不满足 3.11+：$PY（$("$PY" -V 2>&1 || true)）"
  note "使用 CVPLATFORM_PYTHON 指定的解释器"
elif pick_py; then
  note "机器上已有满足 3.11+ 的解释器"
else
  note "机器自带的 Python 版本过低（$( (command -v python3 >/dev/null 2>&1 && python3 -V 2>&1) || echo '未找到 python3')），开始安装 Python 3.12 …"
  if [[ $HAS_SUDO -eq 1 ]]; then
    install_py312_apt || true
    pick_py || true
    if ! py_ok "$PY"; then
      install_py312_deadsnakes || true
      pick_py || true
    fi
  fi
  if ! py_ok "$PY"; then
    install_py312_uv || true
  fi
  if ! py_ok "$PY"; then
    cat >&2 <<'EOF'
!! 无法自动获得 Python 3.11+。请任选一种方式，然后重跑本脚本（脚本可重复执行）：
     a) 有管理员权限时手动装： sudo apt-get install -y software-properties-common
       sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get update
       sudo apt-get install -y python3.12 python3.12-venv
     b) 机器能访问外网时用官方独立解释器：
       curl -LsSf https://astral.sh/uv/install.sh | sh && ~/.local/bin/uv python install 3.12
     c) 已有 conda： conda create -y -n cvp python=3.12 && 用 conda run 或直接指定解释器
        CVPLATFORM_PYTHON=$HOME/miniconda3/envs/cvp/bin/python bash deploy/user/bootstrap.sh <发布目录> --port 80
   另一个可行方向是让应用支持 3.10（改掉 datetime.UTC 的唯一用法），这属于代码改动，需要单独授权。
EOF
    exit 1
  fi
fi
note "使用解释器：$PY（$("$PY" -V 2>&1)）"
if ! "$PY" -m venv --help >/dev/null 2>&1; then
  if [[ $HAS_SUDO -eq 1 ]]; then
    note "venv 模块不可用，尝试安装对应的 venv 包 …"
    sudo apt-get install -y -qq "python$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')-venv" \
      || sudo apt-get install -y -qq python3-venv \
      || fail "无法安装 venv 包，请让管理员处理（或改用 conda 环境）"
  else
    fail "Python 缺少 venv 模块，请让管理员安装 python3-venv（或改用 conda 环境）"
  fi
fi
# 把选定解释器传给 install.sh：否则它会自己再挑一次，可能又挑回到系统自带的低版本
export CVPLATFORM_PYTHON="$PY"

log "2/5 端口 $PORT 的绑定授权（必须赶在首次启动之前）"
BIND_OK=1
SYSTEMD_UNIT=0
if [[ $PORT -lt 1024 ]]; then
  if [[ $EUID -eq 0 ]]; then
    note "当前是 root，可直接绑定"
  elif [[ $HAS_SYSTEMD -eq 1 && $HAS_SUDO -eq 1 ]]; then
    note "生成 systemd 单元并授予 CAP_NET_BIND_SERVICE（推荐）"
    # 两个细节：
    #   1) User=/Group= 用数字 ID：这台机器的用户名含 @ 等字符，数字 ID 不会有歧义；
    #   2) 环境文件必须是 KEY=value 纯文本——systemd 的 EnvironmentFile 不是 shell，
    #      遇到 `export XXX=1` 会记 “invalid variable name” 并整行忽略（实测报错原文如此）。
    UNIT=/etc/systemd/system/$SERVICE_NAME.service
    sudo bash -c "cat > '$UNIT'" <<EOF
[Unit]
Description=CVPlatform (FastAPI + Uvicorn, frontend served by backend)
After=network.target

[Service]
Type=simple
User=$(id -u)
Group=$(id -g)
WorkingDirectory=$APP_DIR
EnvironmentFile=-$APP_DIR/env.sh
Environment=PYTHONPATH=$APP_DIR/backend
Environment=PYTHONUNBUFFERED=1
# 关键：允许非 root 用户绑定 80 这类特权端口，且必须在进程启动前就生效
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn app.main:app --app-dir $APP_DIR/backend --host 0.0.0.0 --port $PORT --workers 1
Restart=always
RestartSec=3
MemoryMax=800M
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    # 先只 enable 不 start：此时虚拟环境还没建，现在启动只会反复失败重启
    sudo systemctl daemon-reload || fail "systemctl daemon-reload 失败"
    sudo systemctl enable $SERVICE_NAME >/dev/null 2>&1 || true
    SYSTEMD_UNIT=1
    note "单元已就位并设为开机自启（暂不启动，等 install.sh 建好虚拟环境）"
  else
    note "没有免密 sudo：$PORT 是特权端口，需要部署完成后由管理员授权一次（见第 4 步）"
    BIND_OK=0
  fi
fi

log "3/5 部署应用（代码、前端、数据库、依赖）"
bash "$SCRIPT_DIR/install.sh" "$RELEASE_DIR" --port "${PORT_FOR_INSTALL:-$PORT}"
note "已按端口 $PORT 完成部署与首次自检"

log "4/5 启动与验证"
if [[ $SYSTEMD_UNIT -eq 1 ]]; then
  sudo systemctl restart $SERVICE_NAME
  sleep 4
  note "服务状态：$(systemctl is-active $SERVICE_NAME 2>/dev/null || true)"
  note "此路径下请用 systemctl 管理：systemctl status|restart|stop $SERVICE_NAME"
elif [[ $PORT -lt 1024 && $EUID -ne 0 ]]; then
  note "只差一步授权。请执行下面这一条（给虚拟环境的解释器加绑定能力），然后重跑本脚本："
  echo
  echo "    sudo setcap 'cap_net_bind_service=+ep' $APP_DIR/.venv/bin/python3*"
  echo
  BIND_OK=0
else
  bash "$APP_DIR/deploy/user/ctl.sh" restart || true
fi

HEALTH="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true)"
note "健康检查 http://127.0.0.1:$PORT/api/health → ${HEALTH:-无响应}"
[[ "$HEALTH" == "200" ]] && BIND_OK=1 || BIND_OK=0

log "5/5 结果"
if [[ $BIND_OK -eq 1 ]]; then
  note "站点已在端口 $PORT 提供服务（页面与接口同一进程）。"
  note "公网访问需要在安全组/防火墙放行 $PORT。"
  curl -s "http://127.0.0.1:$PORT/api/stats/coverage" | head -c 240; echo
else
  note "端口 $PORT 尚未正常提供服务。最近 20 行日志（先看这里，失败原因通常一目了然）："
  echo
  if [[ $SYSTEMD_UNIT -eq 1 ]]; then
    sudo journalctl -u $SERVICE_NAME -n 20 --no-pager 2>/dev/null || true
  else
    tail -n 20 "$APP_DIR/logs/app.log" 2>/dev/null || echo "  （暂无日志文件）"
  fi
  echo
  note "常见原因：端口被占用、特权端口未授权、数据库路径不可写。"
fi
