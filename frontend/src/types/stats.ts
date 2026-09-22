/**
 * 统计接口的领域类型。
 *
 * 字段与后端响应**逐字对应**（沿用 snake_case），与 开发设计与验收.md 第 7.5 节的契约一致，
 * 不另做一层字段映射，避免两套表示互相漂移。缺失值一律是 null：界面必须区分
 * 「没有数据」（null + has_data false）与「有样本但计数为 0」（0）。
 */

export interface StatsScopeRef {
  conferences: string[]
  year_from: number | null
  year_to: number | null
}

/** 被排除在分母之外的论文数；四个桶互斥 */
export interface StatsExcluded {
  pending: number
  failed: number
  stale: number
  invalid_title: number
}

/** 「未归类」的规模：不参与榜单排序，但必须展示 */
export interface StatsUnmapped {
  applies: boolean
  keyword_total: number
  paper_count: number
  share: number | null
}

export interface StatsCoverage {
  conference_years: number
  sampled: boolean
  sample_limit_per_conference_year: number | null
  /** sampled 的判定依据：meta / counts_match_limit / unknown */
  sample_basis: string
  missing_conference_years: { conference: string; year: number }[]
}

export interface StatsItem {
  rank: number
  /** 主题 slug 或关键词归一形式，用于查询参数 */
  key: string
  name: string
  group: string | null
  is_unmapped: boolean
  count: number
  /** 占比（百分数）；分母为 0 时为 null */
  share: number | null
}

export interface StatsSummary {
  scope: StatsScopeRef
  denominator: number
  total_sample: number
  keyword_total: number
  hottest: {
    key: string
    name: string
    group: string | null
    count: number
    share: number | null
  } | null
  unmapped_keyword_total: number
  unmapped: StatsUnmapped
  excluded: StatsExcluded
  coverage: StatsCoverage
  data_updated_at: string | null
  years: number[]
  analysis_version: number
  keyword_ruleset_version: string
  has_data: boolean
  group_by: string
}

export interface StatsTop {
  scope: StatsScopeRef
  denominator: number
  total_sample: number
  excluded: StatsExcluded
  items: StatsItem[]
  key_total: number
  unmapped: StatsUnmapped
  has_data: boolean
  limit: number
  limit_truncated: boolean
  group_by: string
  exclude_unmapped: boolean
}

export interface GraphNode {
  key: string
  name: string
  group: string | null
  is_unmapped: boolean
  count: number
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
  source_name: string
  target_name: string
}

export interface StatsGraph {
  scope: StatsScopeRef
  denominator: number
  total_sample: number
  excluded: StatsExcluded
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** 是否因节点上限而截断（图例处必须标注展示范围） */
  truncated: boolean
  node_total: number
  edge_total: number
  unmapped: StatsUnmapped
  exclude_unmapped: boolean
  limit: number
  min_edge: number
  has_data: boolean
  group_by: string
}

export interface TrendPoint {
  conference: string
  year: number
  /** 无样本时为 null，不写成 0 */
  count: number | null
  denominator: number
  share: number | null
  has_data: boolean
  reason: string | null
}

export interface TrendSeries {
  key: string
  name: string
  group: string | null
  is_unmapped: boolean
  points: TrendPoint[]
}

export interface StatsTrend {
  scope: StatsScopeRef
  denominator: number
  total_sample: number
  excluded: StatsExcluded
  keys: string[]
  key_total: number
  unmapped: StatsUnmapped
  years: number[]
  conferences: string[]
  series: TrendSeries[]
  coverage: StatsCoverage
  has_data: boolean
  group_by: string
}

/** 统计查询范围（前端侧对象，由 api 层转成查询参数） */
export interface StatsScopeQuery {
  conferences: string[]
  yearFrom: number | null
  yearTo: number | null
}

/**
 * 主题分组配色与名称。
 *
 * 分组取自主题表 `group_name`，与会议颜色是两套独立概念：
 * 会议色表示「哪个会议」，分组色表示「哪个研究方向大类」。
 * 未在表中的分组用中性色，不伪造分组。
 */
export const topicGroupColors: Record<string, string> = {
  perception: 'var(--color-group-perception)',
  three_d: 'var(--color-group-three-d)',
  generative: 'var(--color-group-generative)',
  multimodal: 'var(--color-group-multimodal)',
  video: 'var(--color-group-video)',
  learning: 'var(--color-group-learning)',
  robustness: 'var(--color-group-robustness)',
  efficiency: 'var(--color-group-efficiency)',
  application: 'var(--color-group-application)',
}

export const topicGroupLabels: Record<string, string> = {
  perception: '感知与识别',
  three_d: '三维与几何',
  generative: '生成与编辑',
  multimodal: '多模态与语言',
  video: '视频与时序',
  learning: '学习范式与架构',
  robustness: '鲁棒与安全',
  efficiency: '效率与评测',
  application: '应用领域',
}

/** 分组缺省色（主题表没写分组或分组未知时使用） */
export const topicGroupFallbackColor = 'var(--color-group-none)'

export function groupColor(group: string | null): string {
  if (!group) return topicGroupFallbackColor
  return topicGroupColors[group] ?? topicGroupFallbackColor
}

export function groupLabel(group: string | null): string {
  if (!group) return '未分组'
  return topicGroupLabels[group] ?? group
}

/** 图例：只列出当前数据里真实出现的分组，不展示没有数据的分组 */
export function legendForGroups(
  groups: (string | null)[],
): { label: string; color: string; shape: 'dot' }[] {
  const seen = new Set<string>()
  const legend: { label: string; color: string; shape: 'dot' }[] = []
  for (const group of groups) {
    if (group === null || seen.has(group)) continue
    seen.add(group)
    legend.push({ label: groupLabel(group), color: groupColor(group), shape: 'dot' })
  }
  return legend
}

/** 百分比显示：null 表示没有分母，必须显示为「—」而不是 0% */
export function formatShare(share: number | null): string {
  if (share === null) return '—'
  return `${share.toFixed(2)}%`
}

/** 计数显示：null 表示没有样本，必须显示为「—」而不是 0 */
export function formatCount(count: number | null): string {
  if (count === null) return '—'
  return String(count)
}
