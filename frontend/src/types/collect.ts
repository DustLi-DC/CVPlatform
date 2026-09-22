/**
 * 单篇采集的接口类型。
 *
 * 与 src/types/paper.ts 同一约定：这些接口**直接对应后端响应字段**（见 /openapi.json 中
 * LookupResponse / CandidateOut 的定义），因此沿用 snake_case，不再另做一层映射。
 * 只有前端自己构造的请求对象（LookupInput、ConfirmInput）使用 camelCase，
 * 由 src/api/collectApi.ts 统一转换成请求体。
 */

import type { Conference, PaperDetail } from './paper'

/** 本地命中时返回的记录摘要，用于跳转到论文详情页 */
export interface LocalPaperRef {
  id: number
  code: string
  title: string
  conference: Conference
  year: number
}

/**
 * 在线候选。
 *
 * `conference` 为 null 表示来源无法确定会议归属（例如 ECCV 的 DOI 指向出版社），
 * 必须由使用者补充后才能确认导入，界面不允许自动选定。
 */
export interface CollectCandidate {
  source: string
  source_id: string
  title: string
  year: number | null
  conference: Conference | null
  venue: string | null
  doi: string | null
  landing_url: string | null
  pdf_url: string | null
  abstract: string | null
  /** 来源是否没有提供摘要，界面据此提示「摘要缺失」 */
  abstract_missing: boolean
  authors: string[]
  work_type: string | null
  /** 与查询语句的相似度（0—1） */
  match_score: number
  already_exists: boolean
  /** already_exists 为 true 时给出已存在记录的编号 */
  existing_code: string | null
  /** 来源的限制说明，例如「无法确定会议归属」「没有提供摘要」，原样展示 */
  notes: string[]
}

/**
 * 查询结局。前三种是正常返回，后两种对应 HTTP 504 / 502 的真实故障，
 * 与「没有找到」必须分别呈现，不能都写成失败或都写成成功。
 */
export type LookupOutcome =
  | 'local_hit'
  | 'remote_candidates'
  | 'remote_empty'
  | 'remote_timeout'
  | 'remote_unavailable'

export interface LookupResponse {
  outcome: LookupOutcome
  /** 服务端实际使用的查询语句 */
  query: string
  /** 在线检索用到的来源标识；本地命中时为 null */
  source: string | null
  message: string | null
  papers: LocalPaperRef[]
  candidates: CollectCandidate[]
}

/** 单篇采集查询参数（前端侧对象，由 api 层转换为请求体） */
export interface LookupInput {
  title: string
  conference: Conference | null
  year: number | null
}

/** 确认导入某条候选（前端侧对象，由 api 层转换为请求体） */
export interface ConfirmInput {
  title: string
  conference: Conference
  year: number
  source: string
  sourceId: string
  abstract: string
  authors: string[]
  landingUrl: string
  pdfUrl: string
}

/** 确认导入的返回：新建或补齐后的论文详情 */
export type ConfirmResult = PaperDetail

export const lookupOutcomeLabels: Record<LookupOutcome, string> = {
  local_hit: '本地命中',
  remote_candidates: '已获取候选',
  remote_empty: '联网未找到',
  remote_timeout: '联网超时',
  remote_unavailable: '来源不可用',
}

/** 结局徽标配色，与状态画板一致 */
export function lookupOutcomeBadgeClass(outcome: LookupOutcome): string {
  switch (outcome) {
    case 'local_hit':
      return 'badge-ok'
    case 'remote_candidates':
      return 'badge-primary'
    case 'remote_empty':
      return 'badge-neutral'
    case 'remote_timeout':
      return 'badge-warn'
    default:
      return 'badge-danger'
  }
}

/**
 * 候选的唯一键。
 *
 * 来源标识在各自来源内唯一，因此用「来源 + 来源内编号」作为单选与去重的键，
 * 不用数组下标，避免列表顺序变化后选错候选。
 */
export function candidateKey(candidate: CollectCandidate): string {
  return `${candidate.source}:${candidate.source_id}`
}

/** 相似度展示：0—1 的分数转成整数百分比，缺失时不写 0 而写成未知 */
export function matchScoreLabel(score: number): string {
  if (!Number.isFinite(score)) return '未知'
  return `${Math.round(score * 100)}%`
}
