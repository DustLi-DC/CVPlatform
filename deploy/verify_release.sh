#!/usr/bin/env bash
# CVPlatform 发布包预检（在开发机执行，不需要 sudo，不需要服务器）
#
# 用途：上传前确认发布包内容与随机附带的数据库快照可用，避免「传上去才发现包不完整」。
# 与服务器上的 smoke_check.sh 分工不同：这个只检查包本身，不访问网络与线上服务。
#
# 用法：
#   bash deploy/verify_release.sh                                   # 用 data/release 下最新的包
#   bash deploy/verify_release.sh data/release/cvplatform-release-1.0.0.tar.gz

# 自愈：文件若是 CRLF 行尾（从 Windows 打包/解压时常见），转成 LF 的临时文件后重新执行。
# 否则 bash 会把每行末尾的 CR 当命令的一部分，报 $'\r': command not found。
if [ -f "$0" ] && LC_ALL=C grep -q $'\r' "$0" 2>/dev/null; then
  LF_TMP="$(mktemp)"
  tr -d '\r' < "$0" > "$LF_TMP"
  exec bash "$LF_TMP" "$@"
fi

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARBALL="${1:-}"
FAILED=0

fail() { printf '  !! %s\n' "$*"; FAILED=$((FAILED + 1)); }
ok()   { printf '  ok %s\n' "$*"; }

if [[ -z "$TARBALL" ]]; then
  TARBALL="$(ls -t "$ROOT/data/release/"*.tar.gz 2>/dev/null | head -1 || true)"
fi
[[ -n "$TARBALL" && -f "$TARBALL" ]] || { echo "找不到发布包；先执行 bash deploy/make_release.sh 1.0.0 [--with-db]" >&2; exit 2; }

echo "== 发布包：$TARBALL =="
SIZE_MB=$(( $(stat -c %s "$TARBALL" 2>/dev/null || stat -f %z "$TARBALL") / 1024 / 1024 ))
echo "  大小：${SIZE_MB} MB"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
tar -xzf "$TARBALL" -C "$STAGE"
PKG="$(find "$STAGE" -maxdepth 1 -mindepth 1 -type d | head -1)"
[[ -n "$PKG" ]] || { echo "包内没有目录" >&2; exit 2; }

echo
echo "== 1) 必要内容 =="
for item in backend/app/main.py backend/app/data/topics_v1.json frontend/dist/index.html \
            requirements.txt deploy/update.sh deploy/smoke_check.sh deploy/backup_database.py \
            deploy/nginx.conf.example deploy/cvplatform.service.example deploy/env.example; do
  [[ -f "$PKG/$item" ]] && ok "$item" || fail "缺少 $item"
done

echo
echo "== 2) 不应包含的内容 =="
for pattern in '.venv/' 'node_modules/' '__pycache__/' '/tests/' '实施基线.md' '开发设计与验收.md' '博客材料/'; do
  if find "$PKG" -path "*$pattern*" | grep -q .; then
    fail "包内出现不该发布的内容：$pattern"
  else
    ok "无 $pattern"
  fi
done

echo
echo "== 2b) 文本文件行尾必须是 LF =="
PY_BIN="$ROOT/.venv/Scripts/python.exe"
[[ -x "$PY_BIN" ]] || PY_BIN="$(command -v python3 || command -v python || true)"
if [[ -n "$PY_BIN" ]]; then
  if "$PY_BIN" "$ROOT/deploy/normalize_eol.py" "$PKG" --check >/dev/null 2>&1; then
    ok "脚本、Python 与配置模板均为 LF"
  else
    fail "存在 CRLF 行尾（服务器上会报 $'\r' 错误）；详情：bash deploy/verify_release.sh 后见 normalize_eol.py 输出"
    "$PY_BIN" "$ROOT/deploy/normalize_eol.py" "$PKG" --check | sed 's/^/     /' || true
  fi
else
  echo "  -- 本机没有可用的 python，跳过行尾检查"
fi

echo "== 3) 前端产物与本机构建一致 =="
if [[ -d "$ROOT/frontend/dist/assets" ]]; then
  LOCAL="$(cd "$ROOT/frontend/dist/assets" && ls | sort | tr '\n' ' ')"
  PACKED="$(cd "$PKG/frontend/dist/assets" && ls | sort | tr '\n' ' ')"
  [[ "$LOCAL" == "$PACKED" ]] && ok "assets 文件名完全一致" || fail "assets 不一致：本地[$LOCAL] 包内[$PACKED]"
else
  fail "本机没有 frontend/dist，无法比对（请先 npm --prefix frontend run build）"
fi

echo
echo "== 4) 校验和清单 =="
if [[ -f "$PKG/SHA256SUMS.txt" ]]; then
  MISSING=0
  while read -r line; do
    [[ -n "$line" ]] || continue
    sum="${line%% *}"
    file="${line#* }"
    file="${file#\*}"          # Windows/Git Bash 的 sha256sum 会在文件名前加 * 表示二进制模式
    file="${file#./}"
    actual="$( (cd "$PKG" && { shasum -a 256 "./$file" 2>/dev/null || sha256sum "./$file" 2>/dev/null; }) | awk '{print $1}')"
    if [[ "$actual" != "$sum" ]]; then
      fail "$file 校验和不符"
      MISSING=$((MISSING + 1))
    fi
  done < "$PKG/SHA256SUMS.txt"
  [[ $MISSING -eq 0 ]] && ok "$(wc -l < "$PKG/SHA256SUMS.txt") 个文件校验和全部匹配"
else
  fail "缺少 SHA256SUMS.txt"
fi

echo
echo "== 5) 随包数据库快照（若有）=="
DB="$PKG/data/cvplatform.db"
if [[ -f "$DB" ]]; then
  PY="$ROOT/.venv/Scripts/python.exe"
  [[ -x "$PY" ]] || PY="$(command -v python3 || command -v python || true)"
  if [[ -n "$PY" && -x "$PY" ]]; then
    # Windows 上的 Python 打不开 Git Bash 的 /tmp 风格路径，先转成 C:/... 形式
    DB_FOR_PY="$(cygpath -m "$DB" 2>/dev/null || echo "$DB")"
    if "$PY" - "$DB_FOR_PY" <<'PYEOF'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
papers = conn.execute("SELECT COUNT(*) FROM paper").fetchone()[0]
denom = conn.execute("SELECT COUNT(*) FROM v_analysis_paper").fetchone()[0]
topics = conn.execute("SELECT COUNT(*) FROM topic WHERE is_active = 1").fetchone()[0]
version = conn.execute("PRAGMA user_version").fetchone()[0]
integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
print(f"  论文 {papers} 篇 | 分析分母 {denom} | 启用主题 {topics} 个 | 结构版本 v{version} | integrity_check={integrity}")
raise SystemExit(0 if (integrity == "ok" and papers > 0 and denom > 0) else 1)
PYEOF
    then
      ok "数据库快照可用"
    else
      fail "数据库快照不可用"
    fi
  else
    echo "  -- 本机没有可用的 python，跳过数据库检查（可在服务器上传前用 sqlite3 检查）"
  fi
else
  echo "  -- 包内不含数据库（未使用 --with-db）；部署后站点为空库状态，属预期"
fi

echo
if [[ $FAILED -eq 0 ]]; then
  cat <<EOF
预检通过。接下来（在**服务器**上执行，Windows 的 Git Bash 没有 sudo/systemctl）：

  1) 上传发布包（在开发机执行）：
     scp "$TARBALL" <用户>@123.249.79.118:/tmp/

  2) 服务器上解包并更新：
     sudo tar -xzf /tmp/$(basename "$TARBALL") -C /tmp
     sudo bash /tmp/$(basename "$TARBALL" .tar.gz)/deploy/update.sh --release /tmp/$(basename "$TARBALL" .tar.gz) --dry-run
     sudo bash /tmp/$(basename "$TARBALL" .tar.gz)/deploy/update.sh --release /tmp/$(basename "$TARBALL" .tar.gz) --with-db

  3) 线上验收（服务器上）：
     bash /tmp/$(basename "$TARBALL" .tar.gz)/deploy/smoke_check.sh
     bash /tmp/$(basename "$TARBALL" .tar.gz)/deploy/smoke_check.sh http://123.249.79.118
EOF
  exit 0
fi
echo "预检失败 $FAILED 项，请先修好再上传"
exit 1
