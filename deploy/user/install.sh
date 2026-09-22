#!/usr/bin/env bash
# CVPlatform 用户级部署安装（不需要 sudo、不需要 systemd、不需要 Nginx）
#
# 适用场景：只能以普通用户登录的机器（例如 ssh WORK2@65.52.167.95），
# 没有 root 权限装 systemd 服务或配置 Nginx。此时由**后端自己托管前端产物**
# （CVPLATFORM_SERVE_FRONTEND），一个进程同时提供接口与页面。
#
# 目录布局（都在当前用户家目录下，互不干扰）：
#   ~/cvplatform/         代码：backend/、frontend/dist/、deploy/
#   ~/cvplatform-data/    数据库与备份（代码更新不动它）
#   ~/cvplatform/env.sh   环境变量（0600）
#   ~/cvplatform/logs/    运行日志
#
# 用法（在服务器上，先解包发布包）：
#   cd ~ && tar -xzf /tmp/cvplatform-release-1.0.0.tar.gz
#   bash ~/cvplatform-release-1.0.0/deploy/user/install.sh ~/cvplatform-release-1.0.0
#
# 可选参数（也可写进 ~/cvplatform/env.sh 后再执行）：
#   --port 8000        后端监听端口（默认 8000）
#   --no-db            不使用发布包里的数据库快照（保留现有数据库）

set -euo pipefail

# 自愈：CRLF 行尾会让 bash 报 $'\r': command not found
if [ -f "$0" ] && LC_ALL=C grep -q $'\r' "$0" 2>/dev/null; then
  LF_TMP="$(mktemp)"
  tr -d '\r' < "$0" > "$LF_TMP"
  exec bash "$LF_TMP" "$@"
fi

APP_DIR="${CVPLATFORM_APP_DIR:-$HOME/cvplatform}"
DATA_DIR="${CVPLATFORM_DATA_DIR:-$HOME/cvplatform-data}"
SERVICE_NAME="${CVPLATFORM_SERVICE:-cvplatform}"
PORT=8000
USE_DB=1
RELEASE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:-8000}"; shift 2 ;;
    --no-db) USE_DB=0; shift ;;
    -*) echo "未知参数：$1" >&2; exit 2 ;;
    *) RELEASE_DIR="$1"; shift ;;
  esac
done

log()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { echo "!! $*" >&2; exit 1; }

[[ -n "$RELEASE_DIR" && -d "$RELEASE_DIR/backend/app" ]] || fail "请给出发布包解压目录（含 backend/app），例如 bash deploy/user/install.sh ~/cvplatform-release-1.0.0"
[[ -d "$RELEASE_DIR/frontend/dist" ]] || fail "发布包缺少 frontend/dist"

log "1/6 检查 Python"
PY=""
if [[ -n "${CVPLATFORM_PYTHON:-}" ]]; then
  # 允许显式指定解释器（例如机器上只有 conda 环境）
  PY="$CVPLATFORM_PYTHON"
else
  for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$(command -v "$candidate")"; break; fi
  done
fi
[[ -n "$PY" ]] || fail "找不到 Python（需要 3.11+）。若只有 conda，请用 CVPLATFORM_PYTHON=\$HOME/miniconda3/bin/python 重试；若系统自带的是 3.10，请改用 deploy/user/bootstrap.sh 自动安装 3.12"
"$PY" - <<'PYEOF' || fail "Python 版本过低（$("$PY" -V 2>&1)）：需要 3.11+，项目使用 datetime.UTC 等 3.11 起可用的特性。请改用 deploy/user/bootstrap.sh，它会自动安装 Python 3.12"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PYEOF
echo "  使用解释器：$PY（$("$PY" -V 2>&1)）"

log "2/6 创建目录与虚拟环境"
mkdir -p "$APP_DIR" "$DATA_DIR" "$APP_DIR/logs"
VENV_PY="$APP_DIR/.venv/bin/python"
# 复用已有虚拟环境前先核对解释器版本：早期用系统自带 3.10 建过的话必须重建，否则启动时才报错
if [[ -x "$VENV_PY" ]] && "$VENV_PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  echo "  复用已存在的 $APP_DIR/.venv（$("$VENV_PY" -V 2>&1)）"
elif [[ -d "$APP_DIR/.venv" ]]; then
  echo "  已有虚拟环境不满足 3.11+（$("$VENV_PY" -V 2>&1 || echo '无法执行')），重建"
  rm -rf "$APP_DIR/.venv"
  "$PY" -m venv "$APP_DIR/.venv" || fail "创建虚拟环境失败（缺少 python3-venv 时请联系管理员，或用 conda 环境手动创建）"
  VENV_PY="$APP_DIR/.venv/bin/python"
  echo "  已创建 $APP_DIR/.venv（$("$VENV_PY" -V 2>&1)）"
else
  "$PY" -m venv "$APP_DIR/.venv" || fail "创建虚拟环境失败（缺少 python3-venv 时请联系管理员，或用 conda 环境手动创建）"
  echo "  已创建 $APP_DIR/.venv（$("$VENV_PY" -V 2>&1)）"
fi

log "3/6 安装后端依赖"
# 依赖与线上一致；此处可能需要访问 PyPI。网络受限时可先用 --skip-deps 手工处理。
if [[ "${CVPLATFORM_SKIP_DEPS:-0}" == "1" ]]; then
  echo "  按 CVPLATFORM_SKIP_DEPS=1 跳过"
else
  "$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1 || echo "  （升级 pip 失败，继续）"
  "$VENV_PY" -m pip install -r "$RELEASE_DIR/requirements.txt" || fail "依赖安装失败：请检查能否访问 PyPI（或设置代理后重试）"
fi

log "4/6 部署代码与前端产物"
rm -rf "$APP_DIR/backend" "$APP_DIR/frontend"
mkdir -p "$APP_DIR/frontend"
cp -a "$RELEASE_DIR/backend" "$APP_DIR/backend"
cp -a "$RELEASE_DIR/frontend/dist" "$APP_DIR/frontend/dist"
rm -rf "$APP_DIR/deploy" && mkdir -p "$APP_DIR/deploy"
cp -a "$RELEASE_DIR/deploy/." "$APP_DIR/deploy/"
chmod +x "$APP_DIR/deploy/user/"*.sh 2>/dev/null || true
echo "  代码 → $APP_DIR/backend；前端 → $APP_DIR/frontend/dist"

log "5/6 数据库与配置"
DB_PATH="$DATA_DIR/cvplatform.db"
if [[ ! -f "$DB_PATH" ]]; then
  if [[ "$USE_DB" == "1" && -f "$RELEASE_DIR/data/cvplatform.db" ]]; then
    cp -f "$RELEASE_DIR/data/cvplatform.db" "$DB_PATH"
    echo "  已使用发布包内的数据库快照（29,072 篇真实论文）"
  else
    echo "  未提供快照，将在首次启动时新建空库（站点为空数据状态）"
  fi
else
  echo "  已存在数据库，保留现有数据：$DB_PATH"
fi
cat > "$APP_DIR/env.sh" <<EOF
# CVPlatform 用户级部署环境变量（由 deploy/user/install.sh 生成）
#
# 注意：这里必须是纯 KEY=value，不能写 export —— systemd 的 EnvironmentFile 不是 shell，
# 遇到 export 前缀会记 “invalid variable name” 并整行忽略，导致服务拿到空的数据库路径。
# ctl.sh 读取本文件时用 set -a 自动导出，所以普通用户方式启动也不受影响。
CVPLATFORM_ENV=production
CVPLATFORM_DB_PATH=$DB_PATH
# 由后端直接托管前端产物：单进程同时提供接口与页面（无需 Nginx）
CVPLATFORM_SERVE_FRONTEND=$APP_DIR/frontend/dist
CVPLATFORM_PORT=$PORT
PYTHONPATH=$APP_DIR/backend
AUTO_RESUME_TASKS=true
HTTP_INTERVAL_SECONDS=0.5
EOF
chmod 600 "$APP_DIR/env.sh"
echo "  已写入 $APP_DIR/env.sh（端口 $PORT）"

log "6/6 启动并自检"
# 若 bootstrap 已经装好 systemd 单元，就交给 systemd 启动：绑定特权端口所需的能力由它授予
if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]]; then
  echo "  检测到 systemd 单元 $SERVICE_NAME，用 systemctl 启动"
  if [[ $EUID -eq 0 ]]; then
    systemctl restart "$SERVICE_NAME" || echo "  !! systemctl 启动失败，继续看自检结果"
  else
    sudo -n systemctl restart "$SERVICE_NAME" 2>/dev/null \
      || systemctl restart "$SERVICE_NAME" 2>/dev/null \
      || echo "  !! 无法通过 systemctl 重启（权限不足），请用 bootstrap.sh 或在第 4 步授权后重试"
  fi
else
  # 自检失败不算致命：普通用户绑特权端口时这里必然失败，由 bootstrap 的第 4 步接手
  bash "$APP_DIR/deploy/user/ctl.sh" restart || echo "  !! 启动失败（见下面的自检与日志）"
fi
sleep 4
bash "$APP_DIR/deploy/user/ctl.sh" status || true
echo
echo "  本机自检："
curl -s -o /dev/null -w "    /            → %{http_code}\n" "http://127.0.0.1:$PORT/" || true
curl -s -o /dev/null -w "    /trends      → %{http_code}\n" "http://127.0.0.1:$PORT/trends" || true
curl -s -o /dev/null -w "    /api/health  → %{http_code}\n" "http://127.0.0.1:$PORT/api/health" || true
curl -s "http://127.0.0.1:$PORT/api/stats/coverage" 2>/dev/null | head -c 200 || true; echo

if [[ "$PORT" -lt 1024 ]]; then
  cat <<EOF

注意：端口 $PORT 是特权端口（<1024）。若上面的自检里 / 或 /api/health 不是 200，
说明当前用户无权绑定（日志会显示 Permission denied）。两种解法：
  a) 用 deploy/user/bootstrap.sh 重跑一次，它会按可用权限生成带
     AmbientCapabilities=CAP_NET_BIND_SERVICE 的 systemd 单元，或给出 setcap 命令；
  b) 换高位端口（如 8000）并用 SSH 端口转发访问。
EOF
fi

cat <<EOF

部署完成。接下来：
- 查看状态/日志：bash $APP_DIR/deploy/user/ctl.sh status|logs
- 重启/停止：    bash $APP_DIR/deploy/user/ctl.sh restart|stop
- 对外访问需要放行端口 $PORT（安全组/防火墙）。若只能通过他人机器访问，可用 SSH 端口转发：
    ssh -L 8080:127.0.0.1:$PORT WORK2@65.52.167.95
  然后在本地浏览器打开 http://127.0.0.1:8080
EOF
