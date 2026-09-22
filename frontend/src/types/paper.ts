/**
 * 论文领域类型：对应 开发设计与验收.md 第 3 章与第 7.2 节的数据契约。
 * 演示数据与后续真实接口共用这些类型，接入接口时不需要改视图层的类型。
 */

export type Conference = 'CVPR' | 'ICCV' | 'ECCV'

/** 数据完整性状态；界面徽标由 displayStatus 统一给出 */
export type DataStatus = 'complete' | 'review' | 'failed'

/** 摘要可用性 */
export type AbstractStatus = 'present' | 'missing'

/** 关键词处理状态 */
export type KeywordStatus = 'pending' | 'running' | 'done' | 'failed'

/**
 * 服务端计算的展示徽标，优先级：failed → review → abstract_missing → complete。
 * 前端直接展示该值，不在本地重复实现优先级逻辑。
 */
export type DisplayStatus = 'complete' | 'review' | 'abstract_missing' | 'failed'

export type KeywordOrigin = 'author' | 'system'

export interface PaperKeyword {
  name: string
  origin: KeywordOrigin
  /** 归并到的主題；未归类为 null，界面标注“未归类” */
  topic: string | null
}

export interface PaperSourceRef {
  source: string
  sourceId: string
  url: string | null
  retrievedAt: string | null
}

export interface Paper {
  id: number
  code: string
  /** 编号分配时的会议年份与当前值不一致时为 true */
  codeScopeMismatch: boolean
  codeNote: string | null
  title: string
  conference: Conference
  year: number
  displayStatus: DisplayStatus
  abstractStatus: AbstractStatus
  keywordStatus: KeywordStatus
  /** 摘要缺失时为 null；不写空串、不写占位文本 */
  abstract: string | null
  /** 来源提供的关键词（作者关键词），只展示、不参与统计 */
  sourceKeywords: string[]
  /** 系统提取的关键词，经主题归并后参与统计 */
  systemKeywords: string[]
  /** 列表与详情共用的关键词视图（含来源与主题标注） */
  keywords: PaperKeyword[]
  landingUrl: string | null
  pdfUrl: string | null
  sources: PaperSourceRef[]
  retrievedAt: string | null
  updatedAt: string | null
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

export type MatchMode = 'fuzzy' | 'exact'

export type PaperSortField = 'code' | 'title' | 'year' | 'conference' | 'createdAt'

export type SortOrder = 'asc' | 'desc'

export interface PaperQuery {
  q: string
  match: MatchMode
  /** 多会议筛选；空数组表示全部会议 */
  conferences: Conference[]
  yearFrom: number | null
  yearTo: number | null
  keyword: string
  topic: string
  /** 单页条数；原型为 8 条 */
  page: number
  pageSize: number
  sort: PaperSortField
  order: SortOrder
}

export interface PaperPage {
  items: Paper[]
  total: number
  page: number
  pageSize: number
  pages: number
}

/** 会议固定色，全站一致 */
export const conferenceColors: Record<Conference, string> = {
  CVPR: 'var(--color-conf-cvpr)',
  ICCV: 'var(--color-conf-iccv)',
  ECCV: 'var(--color-conf-eccv)',
}

export const allConferences: Conference[] = ['CVPR', 'ICCV', 'ECCV']
