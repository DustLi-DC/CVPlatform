/**
 * 论文领域类型。
 *
 * 这里的 PaperPaperListItem / PaperDetail / PaperPage 等**直接对应后端响应字段**，
 * 因此沿用 snake_case 命名，不再另做一层映射：字段名与 开发设计与验收.md 第 7.2 节的
 * 契约、以及 /openapi.json 中的定义完全一致，避免出现两套表示而互相漂移。
 *
 * 仅在前端构造、不作为请求体的参数对象（PaperQuery、PaperInput）使用 camelCase，
 * 由 src/api/paperApi.ts 统一转换为查询参数或请求体，转换只发生在一个文件里。
 */

export type Conference = 'CVPR' | 'ICCV' | 'ECCV'

/** 服务端计算的展示徽标，优先级：failed → review → abstract_missing → complete */
export type DisplayStatus = 'complete' | 'review' | 'abstract_missing' | 'failed'

export type AbstractStatus = 'present' | 'missing'

export type KeywordStatus = 'pending' | 'running' | 'done' | 'failed'

export type KeywordOrigin = 'author' | 'system'

export interface PaperKeyword {
  name: string
  origin: KeywordOrigin
  /** 归并到的主題；未归类为 null，界面标注「未归类」 */
  topic: string | null
  /** 主题分组（用于取分组配色）；未归类为 null */
  topic_group: string | null
}

export interface PaperSourceRef {
  source: string
  source_id: string
  url: string | null
  retrieved_at: string | null
}

export interface PaperListItem {
  id: number
  code: string
  /** 编号分配时的会议年份与当前值不一致时为 true */
  code_scope_mismatch: boolean
  code_note: string | null
  title: string
  conference: Conference
  year: number
  display_status: DisplayStatus
  abstract_status: AbstractStatus
  keyword_status: KeywordStatus
  /** 含作者关键词与当前版本的系统关键词 */
  keywords: PaperKeyword[]
  landing_url: string | null
  pdf_url: string | null
}

export interface PaperDetail extends PaperListItem {
  /** 摘要缺失时为 null；不写空串、不写占位文本 */
  abstract: string | null
  authors: string[]
  source_keywords: string[]
  system_keywords: string[]
  sources: PaperSourceRef[]
  retrieved_at: string | null
  updated_at: string | null
}

export interface QueryScope {
  conferences: string[]
  year_from: number | null
  year_to: number | null
}

/** 统计口径跳转时实际生效的约束（由服务端回显） */
export interface StatsMode {
  keyword_origin: string
  ruleset_version: string
  in_analysis_set: boolean
}

export interface PaperPage {
  items: PaperListItem[]
  total: number
  page: number
  page_size: number
  pages: number
  scope: QueryScope
  stats_mode: StatsMode | null
}

export type MatchMode = 'fuzzy' | 'exact'

export type PaperSortField = 'code' | 'title' | 'year' | 'conference' | 'created_at'

export type SortOrder = 'asc' | 'desc'

/** 列表查询条件（前端侧对象，由 api 层转换为查询参数） */
export interface PaperQuery {
  q: string
  match: MatchMode
  conferences: Conference[]
  yearFrom: number | null
  yearTo: number | null
  keyword: string
  topic: string
  dataStatus: '' | 'complete' | 'review' | 'failed'
  keywordStatus: '' | KeywordStatus
  /**
   * 来自统计页的跳转：后端会强制只算系统关键词、只认当前规则版本并限制在分析集合内，
   * 使列表条数与统计计数一致（开发设计与验收.md 第 7.5 节）。
   */
  fromStats: boolean
  sort: PaperSortField
  order: SortOrder
  page: number
  pageSize: number
}

/** 新增/编辑论文的入参（前端侧对象，由 api 层转换为请求体） */
export interface PaperInput {
  title: string
  conference: Conference
  year: number
  abstract: string
  sourceKeywords: string[]
  landingUrl: string
  pdfUrl: string
}

/** 新增论文时列表里不返回的关键词明细（由 source_keywords 单列提供） */
export interface DuplicateInfo {
  id: number
  code: string
  title: string
  conference: string
  year: number
}

export const displayStatusLabels: Record<DisplayStatus, string> = {
  complete: '已入库',
  review: '待复核',
  abstract_missing: '摘要缺失',
  failed: '采集失败',
}

export const keywordStatusLabels: Record<KeywordStatus, string> = {
  pending: '待处理',
  running: '处理中',
  done: '已处理',
  failed: '处理失败',
}

/** 会议固定色，全站一致；与主题分组色是两套独立概念 */
export const conferenceColors: Record<Conference, string> = {
  CVPR: 'var(--color-conf-cvpr)',
  ICCV: 'var(--color-conf-iccv)',
  ECCV: 'var(--color-conf-eccv)',
}

export const allConferences: Conference[] = ['CVPR', 'ICCV', 'ECCV']

/**
 * 关键词处理状态徽标。
 *
 * 列表接口的 keywords 同时包含作者关键词与当前版本的系统关键词，
 * 因此「已处理但关键词为空」可以据此判断，不需要额外字段。
 */
export function keywordBadgeFor(paper: PaperListItem): KeywordStatus | 'empty' {
  if (paper.keyword_status !== 'done') return paper.keyword_status
  const hasSystemKeyword = paper.keywords.some((item) => item.origin === 'system')
  return hasSystemKeyword ? 'done' : 'empty'
}
