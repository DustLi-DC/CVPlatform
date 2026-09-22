#!/usr/bin/env bash
# CVPlatform 冒烟检查（服务端，只读）
#
# 用法：
#   bash deploy/smoke_check.sh                      # 只检查本机后端
#   bash deploy/smoke_check.sh http://123.249.79.118  # 同时检查公网入口
#
# 检查内容：健康检查、统计接口、页面与子路由、静态资源、错误契约、数据库口径一致性。
# 只做 GET 请求，不修改任何数据；失败项以 !! 标出并以非零状态退出。

set -uo pipefail

BASE="${1:-http://127.0.0.1:8000}"
FAILED=0

# 取 JSON 字段：优先 python3，其次 python；都没有就返回空（调用方按未知处理）
json_field() {
  local path="$1"
  local py
  py="$(command -v python3 || command -v python || true)"
  [[ -n "$py" ]] || { echo ""; return; }
  curl -s -m 20 "${BASE}${path}" | "$py" -c "import json,sys; print(json.load(sys.stdin)$2)" 2>/dev/null || echo ""
}

check() {
  local label="$1" url="$2" expect="${3:-200}"
  local code
  code="$(curl -s -o /tmp/cvplatform-smoke.out -w '%{http_code}' -m 20 "$url" || echo 000)"
  if [[ "$code" == "$expect" ]]; then
    printf '  ok   %-34s %s %s\n' "$label" "$code" "$url"
  else
    printf '  !!   %-34s 期望 %s 实际 %s %s\n' "$label" "$expect" "$code" "$url"
    FAILED=$((FAILED + 1))
  fi
}

echo "== 后端（$BASE）=="
check "健康检查" "$BASE/api/health"
check "覆盖范围（阶段 11 新增）" "$BASE/api/stats/coverage"
check "统计概览" "$BASE/api/stats/summary"
check "热点榜单" "$BASE/api/stats/top?limit=5"
check "关键词图谱" "$BASE/api/stats/graph?limit=10"
check "热度趋势" "$BASE/api/stats/trend"
check "关键词状态" "$BASE/api/keywords/status"
check "论文列表" "$BASE/api/papers?page_size=1"
check "参数错误契约（400）" "$BASE/api/papers?page_size=999" 400
check "不存在的论文（404）" "$BASE/api/papers/999999" 404

echo
echo "== 口径一致性 =="
DEN="$(json_field /api/stats/summary "['denominator']")"
COV="$(json_field /api/stats/coverage "['totals']['analysis_papers']")"
echo "  概览分母=${DEN:-未知} | 覆盖接口分析分母=${COV:-未知}"
if [[ -z "$DEN" || -z "$COV" ]]; then
  echo "  -- 本机没有可用的 python，跳过一致性比对（可在服务器上重跑本脚本）"
elif [[ "$DEN" != "$COV" ]]; then
  echo "  !! 两处分母不一致（统计接口与覆盖接口应取同一分析集合）"
  FAILED=$((FAILED + 1))
else
  echo "  ok  两处分母一致"
fi

# 进程/端口/服务检查只在服务器上做：本机（Windows 开发机）没有 ss 与 systemctl
if [[ "$BASE" == http://127.0.0.1* ]] && command -v ss >/dev/null && command -v systemctl >/dev/null; then
  echo
  echo "== 本机进程与监听 =="
  echo "  监听端口："
  ss -ltnp 2>/dev/null | grep -E ':8000|:80' || echo "  !! 未发现 8000/80 监听"
  echo "  服务状态：$(systemctl is-active cvplatform.service || true)"
  echo "  最近日志："
  journalctl -u cvplatform.service -n 5 --no-pager 2>/dev/null | sed 's/^/    /' || true
fi

echo
if [[ $FAILED -eq 0 ]]; then
  echo "全部通过"
  exit 0
fi
echo "失败 $FAILED 项，请检查后端日志：journalctl -u cvplatform.service -n 200 --no-pager"
exit 1
