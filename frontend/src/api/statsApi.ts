/**
 * 统计接口。
 *
 * 请求集中在 api 层，与 paperApi 共用统一的错误解析（apiRequest）。
 * 所有范围参数拼接只在这里发生，页面不拼 URL。
 */
import { apiRequest } from './paperApi'
import type {
  StatsGraph,
  StatsScopeQuery,
  StatsSummary,
  StatsTop,
  StatsTrend,
} from '../types/stats'

const BASE = '/api/stats'

function toSearchParams(scope: StatsScopeQuery, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams()
  if (scope.conferences.length) params.set('conference', scope.conferences.join(','))
  if (scope.yearFrom !== null) params.set('year_from', String(scope.yearFrom))
  if (scope.yearTo !== null) params.set('year_to', String(scope.yearTo))
  for (const [key, value] of Object.entries(extra)) {
    if (value) params.set(key, value)
  }
  return params.toString()
}

export async function fetchSummary(scope: StatsScopeQuery): Promise<StatsSummary> {
  return apiRequest<StatsSummary>(`${BASE}/summary?${toSearchParams(scope)}`)
}

export async function fetchTop(
  scope: StatsScopeQuery,
  options: { limit?: number; excludeUnmapped?: boolean } = {},
): Promise<StatsTop> {
  const extra: Record<string, string> = {}
  if (options.limit !== undefined) extra.limit = String(options.limit)
  if (options.excludeUnmapped === false) extra.exclude_unmapped = 'false'
  return apiRequest<StatsTop>(`${BASE}/top?${toSearchParams(scope, extra)}`)
}

export async function fetchGraph(
  scope: StatsScopeQuery,
  options: { limit?: number; minEdge?: number } = {},
): Promise<StatsGraph> {
  const extra: Record<string, string> = {}
  if (options.limit !== undefined) extra.limit = String(options.limit)
  if (options.minEdge !== undefined) extra.min_edge = String(options.minEdge)
  return apiRequest<StatsGraph>(`${BASE}/graph?${toSearchParams(scope, extra)}`)
}

export async function fetchTrend(
  scope: StatsScopeQuery,
  options: { keys?: string[] } = {},
): Promise<StatsTrend> {
  const extra: Record<string, string> = {}
  if (options.keys?.length) extra.keys = options.keys.join(',')
  return apiRequest<StatsTrend>(`${BASE}/trend?${toSearchParams(scope, extra)}`)
}
