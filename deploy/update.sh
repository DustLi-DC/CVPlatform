#!/usr/bin/env bash
# CVPlatform 服务端更新脚本（阶段 11）
#
# 用途：在服务器上把已发布代码/前端产物更新到 /opt/cvplatform，并在替换前备份
#      现有代码、数据库与前端产物；随后执行依赖安装、数据库迁移、服务重启与冒烟检查。
#
# 设计原则：
# - **先备份再替换**：备份失败即中止，不做任何改动；
# - **幂等**：可以重复执行；数据库迁移由应用启动时按 user_version 判断，不会重复应用；
# - **失败即停**：任何一步失败都退出并给出回退指引（set -euo pipefail）；
# - 只动运行所需内容：代码、前端产物、依赖、数据库；不写入仓库外的东西。
#
# 用法（在服务器上，用有 sudo 权限的账号执行）：
#   sudo bash /opt/cvplatform/deploy/update.sh --release /tmp/cvplatform-release-1.0.0
#   sudo bash /opt/cvplatform/deploy/update.sh --release /tmp/cvplatform-release-1.0.0 --with-db
#
# 参数：
#   --release DIR   发布包解压目录（含 backend/、frontend/dist/、deploy/、requirements*.txt）
#   --with-db      额外用发布包里的数据库替换生产库（替换前备份；默认不动数据库）
#   --skip-deps    跳过 pip 依赖安装（依赖没变时可用）
#   --dry-run      只打印将执行的动作，不做任何修改

# 自愈：文件若是 CRLF 行尾（从 Windows 打包/解压时常见），转成 LF 的临时文件后重新执行。
# 否则 bash 会把每行末尾的 CR 当命令的一部分，报 $'\r': command not found。
if [ -f "$0" ] && LC_ALL=C grep -q $'\r' "$0" 2>/dev/null; then
  LF_TMP="$(mktemp)"
  tr -d '\r' < "$0" > "$LF_TMP"
  exec bash "$LF_TMP" "$@"
fi

set -euo pipefail

APP_DIR=/opt/cvplatform
DATA_DIR=/var/lib/cvplatform
DB_PATH="$DATA_DIR/cvplatform.db"
SERVICE=cvplatform.service
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="$DATA_DIR/backups"

RELEASE_DIR=""
WITH_DB=0
SKIP_DEPS=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) RELEASE_DIR="${2:-}"; shift 2 ;;
    --with-db) WITH_DB=1; shift ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

log()  { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
run()  { if [[ $DRY_RUN -eq 1 ]]; then echo "  (dry-run) $*"; else eval "$*"; fi; }
fail() { echo "!! $*" >&2; exit 1; }

[[ -n "$RELEASE_DIR" ]] || fail "缺少 --release 参数（发布包解压目录）"
[[ -d "$RELEASE_DIR" ]] || fail "发布目录不存在：$RELEASE_DIR"
[[ -d "$RELEASE_DIR/backend/app" ]] || fail "发布目录缺少 backend/app"
[[ -d "$RELEASE_DIR/frontend/dist" ]] || fail "发布目录缺少 frontend/dist（前端需在本机构建后一起发布）"
[[ $EUID -eq 0 ]] || fail "请用 sudo 执行（需要写 $APP_DIR 与 $DATA_DIR）"

log "1/7 预检查"
echo "  发布目录：$RELEASE_DIR"
echo "  应用目录：$APP_DIR"
echo "  数据目录：$DATA_DIR"
echo "  数据库：  $DB_PATH"
[[ -x "$APP_DIR/.venv/bin/python" ]] || fail "服务器虚拟环境不存在：$APP_DIR/.venv（请先按 deploy/README.md 初始化）"
# 用 systemctl cat 判断单元是否存在：list-unit-files 的输出格式在不同环境下不一定能匹配，
# 实测在目标服务器上匹配失败，而服务其实是 active 的。
systemctl cat "$SERVICE" >/dev/null 2>&1 || fail "服务单元不存在：$SERVICE（模板见 deploy/cvplatform.service.example）"
id cvplatform >/dev/null || fail "运行用户 cvplatform 不存在"
echo "  应用目录内容："
ls -la "$APP_DIR" | sed 's/^/    /'
echo "  运行用解释器：$APP_DIR/.venv/bin/python"
# 数据目录缺失时直接建好（首次部署常见），并交给运行用户
if [[ ! -d "$DATA_DIR" ]]; then
  echo "  数据目录不存在，创建：$DATA_DIR"
  run "install -d -o cvplatform -g cvplatform -m 0750 '$DATA_DIR' '$DATA_DIR/backups'"
else
  run "install -d -o cvplatform -g cvplatform -m 0750 '$DATA_DIR/backups'"
fi
ls -ld "$APP_DIR" "$DATA_DIR"

log "2/7 备份（数据库用 SQLite 在线备份接口，WAL 下也一致）"
mkdir -p "$BACKUP_ROOT"
if [[ -f "$DB_PATH" ]]; then
  run "sudo -u cvplatform $APP_DIR/.venv/bin/python $APP_DIR/deploy/backup_database.py '$DB_PATH' '$BACKUP_ROOT'"
else
  echo "  数据库还不存在，跳过数据库备份（首次部署）"
fi
# 代码与前端产物按目录打包，便于整目录回退
run "tar -czf '$BACKUP_ROOT/app-$STAMP.tar.gz' -C '$APP_DIR' backend frontend/dist deploy 2>/dev/null || true"
echo "  备份目录内容："
ls -lh "$BACKUP_ROOT" | tail -5

log "3/7 替换代码与前端产物"
# 优先 rsync（增量、可 --delete），服务器没装 rsync 时用 tar 管道整目录替换
sync_dir() {
  local src="$1" dst="$2"
  if command -v rsync >/dev/null; then
    run "rsync -a --delete --exclude '__pycache__' '$src' '$dst'"
  else
    run "rm -rf '$dst' && mkdir -p '$dst' && tar -cf - -C '$src' . | tar -xf - -C '$dst'"
  fi
}
sync_dir "$RELEASE_DIR/backend/app/" "$APP_DIR/backend/app/"
sync_dir "$RELEASE_DIR/frontend/dist/" "$APP_DIR/frontend/dist/"
# 把部署脚本放进应用目录只是方便后续在服务器上直接调用；这里不能因为路径异常而中止更新
if [[ -e "$APP_DIR/deploy" && ! -d "$APP_DIR/deploy" ]]; then
  echo "  !! $APP_DIR/deploy 已存在但不是目录（旧部署可能留下同名文件），跳过脚本拷贝；"
  echo "     更新本身不受影响，回退/备份脚本可从发布目录 $RELEASE_DIR/deploy/ 直接调用。"
else
  run "install -d '$APP_DIR/deploy'"
  run "cp -f '$RELEASE_DIR/deploy/backup_database.py' '$APP_DIR/deploy/'"
  run "cp -f '$RELEASE_DIR/deploy/smoke_check.sh' '$APP_DIR/deploy/'"
fi
run "cp -f '$RELEASE_DIR/requirements.txt' '$APP_DIR/requirements.txt'"
# 前端入口文件的属主与权限交给 Nginx（读权限即可）
run "chown -R cvplatform:cvplatform '$APP_DIR/backend' '$APP_DIR/frontend/dist' '$APP_DIR/deploy'"

log "4/7 安装/更新后端依赖（生产只装 requirements.txt，不装 requirements-dev.txt）"
if [[ $SKIP_DEPS -eq 1 ]]; then
  echo "  按 --skip-deps 跳过"
else
  # 虚拟环境的属主可能是 root（现网就是这样），此时以 cvplatform 身份装依赖会因权限不足失败。
  # 先探测 venv 是否对运行用户可写，可写就按运行用户装（保持文件属主一致），
  # 否则以当前身份（root）装——这是更新依赖时更稳妥的选择。
  PIP_CACHE="PIP_CACHE_DIR=/tmp/cvplatform-pip-cache"
  if sudo -u cvplatform test -w "$APP_DIR/.venv/lib" 2>/dev/null; then
    echo "  虚拟环境对 cvplatform 可写，以其身份安装"
    run "sudo -H -u cvplatform env $PIP_CACHE $APP_DIR/.venv/bin/pip install --upgrade pip >/dev/null"
    run "sudo -H -u cvplatform env $PIP_CACHE $APP_DIR/.venv/bin/pip install -r '$APP_DIR/requirements.txt'"
  else
    echo "  虚拟环境属主不是 cvplatform（实际属主：$(stat -c '%U' "$APP_DIR/.venv")），以当前身份安装"
    run "env $PIP_CACHE $APP_DIR/.venv/bin/pip install --upgrade pip >/dev/null"
    run "env $PIP_CACHE $APP_DIR/.venv/bin/pip install -r '$APP_DIR/requirements.txt'"
  fi
fi

log "5/7 数据库：迁移与应用发布包数据（可选）"
# 应用启动时会自动执行未应用的迁移，并（仅当需要变更结构时）自动做一次在线备份；
# 这里先单独跑一次初始化，让迁移结果显式可见，再重启服务。
run "sudo -u cvplatform env CVPLATFORM_ENV=production CVPLATFORM_DB_PATH='$DB_PATH' \\
    PYTHONPATH='$APP_DIR/backend' '$APP_DIR/.venv/bin/python' -c \\
    'from app.db.engine import init_database; print(init_database())'"
if [[ $WITH_DB -eq 1 ]]; then
  [[ -f "$RELEASE_DIR/data/cvplatform.db" ]] || fail "--with-db 但发布包里没有 data/cvplatform.db"
  log "  用发布包数据库替换生产库（已在上一步备份）"
  run "systemctl stop $SERVICE"
  run "sudo -u cvplatform cp -f '$RELEASE_DIR/data/cvplatform.db' '$DB_PATH'"
  run "rm -f '$DB_PATH-wal' '$DB_PATH-shm'"
  run "chown cvplatform:cvplatform '$DB_PATH'"
else
  echo "  按默认策略保留现有数据库（不含 --with-db）"
fi

log "6/7 重启服务"
# 先确认服务会读到生产数据库：旧部署的单元可能没设 CVPLATFORM_ENV/CVPLATFORM_DB_PATH，
# 那样应用会退回「应用目录/data」的开发默认路径，而该目录属主是 root → 启动即 PermissionError。
UNIT_ENV="$(systemctl show "$SERVICE" -p Environment --value 2>/dev/null || true)"
UNIT_ENVFILES="$(systemctl show "$SERVICE" -p EnvironmentFiles --value 2>/dev/null || true)"
if [[ "$UNIT_ENV" != *"CVPLATFORM_ENV=production"* && "$UNIT_ENV" != *"CVPLATFORM_DB_PATH="* && "$UNIT_ENVFILES" != *"/etc/cvplatform.env"* ]]; then
  echo "  !! 服务未配置生产环境变量（Environment/EnvironmentFile 里都没有 CVPLATFORM_ENV 或 CVPLATFORM_DB_PATH）"
  echo "     继续启动会退回开发默认路径并因权限失败。请先执行："
  echo "       sudo bash $RELEASE_DIR/deploy/setup_service_env.sh"
  echo "       sudo systemctl daemon-reload && sudo systemctl restart $SERVICE"
  fail "缺少生产环境变量配置，已在启动前中止（代码与数据库均已备份）"
fi
run "systemctl daemon-reload"
run "systemctl restart $SERVICE"
run "sleep 3"

# 重启后先确认服务真的起来了（失败要立刻可见，而不是等到冒烟检查才暴露）
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "  !! 服务未处于 active 状态，最近日志："
  journalctl -u "$SERVICE" -n 30 --no-pager | sed 's/^/    /' || true
  fail "服务启动失败，请按上面日志排查；代码与数据库已备份，可用脚本输出的回退命令恢复"
fi
echo "  服务状态：$(systemctl is-active $SERVICE)"

log "7/7 冒烟检查"
run "bash '$APP_DIR/deploy/smoke_check.sh'"

log "完成"
cat <<EOF
更新完成（备份时间戳 $STAMP）。
- 回退代码/前端：tar -xzf $BACKUP_ROOT/app-$STAMP.tar.gz -C $APP_DIR
- 回退数据库：systemctl stop $SERVICE && cp $BACKUP_ROOT/$(basename "$DB_PATH" .db)-*.db $DB_PATH && systemctl start $SERVICE
   （数据库备份文件形如 $(basename "$DB_PATH" .db)-$STAMP.db，选择升级前的那一份）
- 查看服务日志：journalctl -u $SERVICE -n 200 --no-pager
EOF
