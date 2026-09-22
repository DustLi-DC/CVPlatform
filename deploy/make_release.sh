#!/usr/bin/env bash
# CVPlatform 发布包制作（本机执行，Windows 的 Git Bash 与 Linux 都可用）
#
# 用法：
#   bash deploy/make_release.sh [版本号] [是否包含数据库]
#   bash deploy/make_release.sh 1.0.0          # 只含代码与前端产物
#   bash deploy/make_release.sh 1.0.0 --with-db  # 额外把 data/cvplatform.db 放进包里的 data/
#
# 产物：data/release/cvplatform-release-<版本>.tar.gz（data/ 已被 .gitignore 忽略）
#      以及同目录的 SHA256SUMS.txt 与 FILES.txt（文件清单，便于人工核对发布内容）

set -euo pipefail

VERSION="${1:-1.0.0}"
WITH_DB="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/data/release"
STAGE="$OUT_DIR/cvplatform-release-$VERSION"
TARBALL="$OUT_DIR/cvplatform-release-$VERSION.tar.gz"

echo "== 预检查 =="
[[ -f "$ROOT/frontend/dist/index.html" ]] || {
  echo "!! 前端产物不存在，请先在仓库根目录执行：npm --prefix frontend run build" >&2
  exit 1
}
[[ -f "$ROOT/backend/requirements.txt" ]] || { echo "!! 缺少 backend/requirements.txt" >&2; exit 1; }

echo "== 收集发布内容到 $STAGE =="
rm -rf "$STAGE"
mkdir -p "$STAGE/backend" "$STAGE/frontend" "$STAGE/deploy"

# 后端：只要运行所需的 app/（含 data/topics_v1.json），不带 tests/ 与 __pycache__
cp -a "$ROOT/backend/app" "$STAGE/backend/app"
find "$STAGE/backend" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp -a "$ROOT/backend/requirements.txt" "$STAGE/requirements.txt"

# 前端：只发布构建产物
cp -a "$ROOT/frontend/dist" "$STAGE/frontend/dist"

# 部署脚本与模板（不含 __pycache__）
cp -a "$ROOT/deploy/." "$STAGE/deploy/"
rm -rf "$STAGE/deploy/__pycache__" "$STAGE/deploy/sample"

# 文档
for doc in README.md codestyle.md 数据覆盖与来源.md; do
  [[ -f "$ROOT/$doc" ]] && cp -a "$ROOT/$doc" "$STAGE/$doc"
done

# 可选：随包数据库
if [[ "$WITH_DB" == "--with-db" ]]; then
  [[ -f "$ROOT/data/cvplatform.db" ]] || { echo "!! 指定了 --with-db 但 data/cvplatform.db 不存在" >&2; exit 1; }
  mkdir -p "$STAGE/data"
  PY="$ROOT/.venv/Scripts/python.exe"
  [[ -x "$PY" ]] || PY="$ROOT/.venv/bin/python"
  # 用项目自带的在线备份脚本生成一致快照（WAL 下直接复制主文件可能不完整）。
  # Windows 的 Git Bash 路径（/c/...）Python 打不开，用 cygpath 转成 C:/... 形式。
  DB_SRC="$(cygpath -m "$ROOT/data/cvplatform.db" 2>/dev/null || echo "$ROOT/data/cvplatform.db")"
  DB_DIR="$(cygpath -m "$STAGE/data" 2>/dev/null || echo "$STAGE/data")"
  "$PY" "$ROOT/deploy/backup_database.py" "$DB_SRC" "$DB_DIR" >/dev/null
  # 备份脚本按时间戳命名，统一改名成发布包约定的 cvplatform.db
  SNAPSHOT="$(ls -t "$STAGE/data/"*.db | head -1)"
  mv -f "$SNAPSHOT" "$STAGE/data/cvplatform.db"
  echo "  数据库快照：$(du -m "$STAGE/data/cvplatform.db" | cut -f1) MB"
fi

echo "== 生成清单与校验和 =="
( cd "$STAGE" && find . -type f | sort > FILES.txt )
( cd "$STAGE" && find . -type f -not -name FILES.txt -not -name SHA256SUMS.txt -exec shasum -a 256 {} \; | sort -k2 > SHA256SUMS.txt 2>/dev/null \
  || find . -type f -not -name FILES.txt -not -name SHA256SUMS.txt -exec sha256sum {} \; | sort -k2 > SHA256SUMS.txt )
echo "  文件数：$(wc -l < "$STAGE/FILES.txt")"

echo "== 打包 =="
( cd "$OUT_DIR" && tar -czf "$TARBALL" "cvplatform-release-$VERSION" )
SIZE_MB=$(( $(stat -c %s "$TARBALL" 2>/dev/null || stat -f %z "$TARBALL") / 1024 / 1024 ))
echo "  产物：$TARBALL（$SIZE_MB MB）"
echo
echo "提示：上传后在服务器上执行"
echo "  sudo tar -xzf cvplatform-release-$VERSION.tar.gz -C /tmp"
echo "  sudo bash /tmp/cvplatform-release-$VERSION/deploy/update.sh --release /tmp/cvplatform-release-$VERSION --dry-run"
