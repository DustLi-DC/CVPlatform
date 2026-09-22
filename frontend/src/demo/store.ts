/**
 * 演示用的内存论文库与查询/写入逻辑。
 *
 * 边界说明：本模块刻意模仿阶段 3 后端接口的行为（筛选、精确/模糊匹配、排序、分页、
 * 去重键冲突），使视图层的写法在接入真实接口后基本不变。它**不持久化**：刷新页面即
 * 回到初始演示数据，所有写入动作都必须提示“仅在本页内存中生效”。
 *
 * 阶段 3/4 接入后端时，把这个模块替换为 src/api/paperApi.ts，视图层调用方式保持一致。
 */
import { computed, ref } from 'vue'

import { demoPapers } from './papers'
import {
  type Conference,
  type DisplayStatus,
  type Paper,
  type PaperKeyword,
  type PaperPage,
  type PaperQuery,
  type SortOrder,
} from '../types/paper'

const papers = ref<Paper[]>(clonePapers(demoPapers))

let nextId = papers.value.length + 1

function clonePapers(source: Paper[]): Paper[] {
  return source.map((paper) => ({
    ...paper,
    sourceKeywords: [...paper.sourceKeywords],
    systemKeywords: [...paper.systemKeywords],
    keywords: paper.keywords.map((keyword) => ({ ...keyword })),
    sources: paper.sources.map((sourceRef) => ({ ...sourceRef })),
  }))
}

/** 归一化标题：只消除大小写、标点与空白差异，与后端 title_normalized 口径一致 */
export function normalizeTitle(title: string): string {
  return title
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()
}

/**
 * 服务端展示徽标的本地等价实现，优先级：failed → review → abstract_missing → complete。
 * 接入接口后改用后端下发的 displayStatus，本函数删除。
 */
export function deriveDisplayStatus(paper: {
  keywordStatus: Paper['keywordStatus']
  displayStatus: DisplayStatus
  abstractStatus: Paper['abstractStatus']
}): DisplayStatus {
  if (paper.displayStatus === 'failed' || paper.keywordStatus === 'failed') return 'failed'
  if (paper.displayStatus === 'review') return 'review'
  if (paper.abstractStatus === 'missing') return 'abstract_missing'
  return 'complete'
}

/** 去重键：会议 + 年份 + 归一化标题 */
export function buildDedupKey(conference: string, year: number, title: string): string {
  return `${conference}|${year}|${normalizeTitle(title)}`
}

function comparePapers(a: Paper, b: Paper, field: PaperQuery['sort'], order: SortOrder): number {
  const direction = order === 'asc' ? 1 : -1
  const pick = (paper: Paper): string | number => {
    if (field === 'year') return paper.year
    if (field === 'title') return normalizeTitle(paper.title)
    if (field === 'conference') return paper.conference
    if (field === 'createdAt') return paper.updatedAt ?? ''
    return paper.code
  }
  const left = pick(a)
  const right = pick(b)
  if (left === right) return a.id - b.id
  return left < right ? -direction : direction
}

export function queryPapers(query: PaperQuery): PaperPage {
  const needle = query.q.trim().toLowerCase()
  const filtered = papers.value.filter((paper) => {
    if (query.conferences.length && !query.conferences.includes(paper.conference)) return false
    if (query.yearFrom !== null && paper.year < query.yearFrom) return false
    if (query.yearTo !== null && paper.year > query.yearTo) return false
    if (query.topic && !paper.keywords.some((keyword) => keyword.topic === query.topic)) {
      return false
    }
    if (query.keyword && !paper.keywords.some((keyword) => keyword.name === query.keyword)) {
      return false
    }
    if (!needle) return true
    if (query.match === 'exact') {
      return (
        normalizeTitle(paper.title) === normalizeTitle(query.q) ||
        paper.code.toLowerCase() === needle
      )
    }
    const haystack = [
      normalizeTitle(paper.title),
      paper.code.toLowerCase(),
      paper.keywords.map((keyword) => keyword.name).join(' ').toLowerCase(),
    ]
    return haystack.some((part) => part.includes(needle))
  })

  const sorted = [...filtered].sort((a, b) => comparePapers(a, b, query.sort, query.order))
  const pages = Math.max(1, Math.ceil(sorted.length / query.pageSize))
  const page = Math.min(Math.max(1, query.page), pages)
  const start = (page - 1) * query.pageSize

  return {
    items: sorted.slice(start, start + query.pageSize),
    total: sorted.length,
    page,
    pageSize: query.pageSize,
    pages,
  }
}

export function getPaper(id: number): Paper | undefined {
  return papers.value.find((paper) => paper.id === id)
}

/** 同主题论文：以该论文系统关键词归属的主题为线索 */
export function relatedPapers(id: number, limit = 3): Paper[] {
  const target = getPaper(id)
  if (!target) return []
  const topics = new Set(
    target.keywords.filter((keyword) => keyword.topic).map((keyword) => keyword.topic),
  )
  return papers.value
    .filter(
      (paper) =>
        paper.id !== id &&
        paper.displayStatus !== 'failed' &&
        paper.keywords.some((keyword) => keyword.topic && topics.has(keyword.topic)),
    )
    .slice(0, limit)
}

export interface PaperInput {
  title: string
  conference: Conference
  year: number
  abstract: string
  sourceKeywords: string[]
  landingUrl: string
  pdfUrl: string
}

export class DuplicatePaperError extends Error {
  readonly existing: Paper

  constructor(existing: Paper) {
    super('duplicate_paper')
    this.name = 'DuplicatePaperError'
    this.existing = existing
  }
}

function toKeywordList(sourceKeywords: string[], systemKeywords: string[]): PaperKeyword[] {
  const authorKeywords: PaperKeyword[] = sourceKeywords.map((name) => ({
    name,
    origin: 'author',
    topic: null,
  }))
  const system: PaperKeyword[] = systemKeywords.map((name) => ({
    name,
    origin: 'system',
    topic: null,
  }))
  return [...system, ...authorKeywords]
}

/** 本地编号分配：会议-年份-序号，只增不减，与后端规则一致（不复用） */
function allocateCode(conference: string, year: number): string {
  const prefix = `${conference}-${year}-`
  const used = papers.value
    .filter((paper) => paper.code.startsWith(prefix))
    .map((paper) => Number.parseInt(paper.code.slice(prefix.length), 10))
    .filter((value) => Number.isFinite(value))
  const next = used.length ? Math.max(...used) + 1 : 1
  return `${prefix}${String(next).padStart(4, '0')}`
}

export function createPaper(input: PaperInput): Paper {
  const dedupKey = buildDedupKey(input.conference, input.year, input.title)
  const existing = papers.value.find(
    (paper) => buildDedupKey(paper.conference, paper.year, paper.title) === dedupKey,
  )
  if (existing) throw new DuplicatePaperError(existing)

  const keywords = toKeywordList(input.sourceKeywords, [])
  const paper: Paper = {
    id: nextId,
    code: allocateCode(input.conference, input.year),
    codeScopeMismatch: false,
    codeNote: null,
    title: input.title,
    conference: input.conference,
    year: input.year,
    displayStatus: 'review',
    abstractStatus: input.abstract ? 'present' : 'missing',
    keywordStatus: 'pending',
    abstract: input.abstract || null,
    sourceKeywords: [...input.sourceKeywords],
    systemKeywords: [],
    keywords,
    landingUrl: input.landingUrl || null,
    pdfUrl: input.pdfUrl || null,
    sources: [],
    retrievedAt: null,
    updatedAt: new Date().toISOString(),
  }
  nextId += 1
  papers.value = [paper, ...papers.value]
  return paper
}

export function updatePaper(id: number, input: PaperInput): Paper {
  const target = getPaper(id)
  if (!target) throw new Error('paper_not_found')

  const dedupKey = buildDedupKey(input.conference, input.year, input.title)
  const conflict = papers.value.find(
    (paper) =>
      paper.id !== id && buildDedupKey(paper.conference, paper.year, paper.title) === dedupKey,
  )
  if (conflict) throw new DuplicatePaperError(conflict)

  const codeScopeMismatch =
    input.conference !== target.conference || input.year !== target.year
      ? true
      : target.codeScopeMismatch

  const contentChanged =
    normalizeTitle(input.title) !== normalizeTitle(target.title) ||
    input.abstract !== (target.abstract ?? '')

  target.title = input.title
  target.conference = input.conference
  target.year = input.year
  target.abstract = input.abstract || null
  target.abstractStatus = input.abstract ? 'present' : 'missing'
  target.landingUrl = input.landingUrl || null
  target.pdfUrl = input.pdfUrl || null
  target.sourceKeywords = [...input.sourceKeywords]
  target.codeScopeMismatch = codeScopeMismatch
  target.codeNote = codeScopeMismatch
    ? '编号为入库时分配，与当前会议年份不一致'
    : null
  if (contentChanged) {
    // 题目或摘要变化会使系统关键词失效，与设计口径一致：退回待处理
    target.keywordStatus = 'pending'
    target.systemKeywords = []
  }
  target.keywords = toKeywordList(target.sourceKeywords, target.systemKeywords)
  target.updatedAt = new Date().toISOString()
  return target
}

export function deletePaper(id: number): void {
  papers.value = papers.value.filter((paper) => paper.id !== id)
}

/** 仅用于演示：重置为初始演示数据 */
export function resetDemoPapers(): void {
  papers.value = clonePapers(demoPapers)
  nextId = papers.value.length + 1
}

export const paperStore = {
  papers: computed(() => papers.value),
  count: computed(() => papers.value.length),
}
