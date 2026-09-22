/**
 * 论文管理接口。
 *
 * - 查询参数与请求体的命名转换集中在本文件，页面不直接拼接 URL。
 * - 后端错误统一为 {"detail": {"code", "message"}}，这里转换成带 code 的 ApiError，
 *   使页面能按错误类型给出不同文案（例如重复冲突要带出已存在的论文编号）。
 */
import type {
  Conference,
  DuplicateInfo,
  PaperDetail,
  PaperInput,
  PaperListItem,
  PaperPage,
  PaperQuery,
} from '../types/paper'

const BASE = '/api/papers'

/** 后端返回的业务错误 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly existing: DuplicateInfo | null
  readonly fields: { field: string; message: string }[]

  constructor(
    status: number,
    code: string,
    message: string,
    existing: DuplicateInfo | null = null,
    fields: { field: string; message: string }[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.existing = existing
    this.fields = fields
  }

  /** 是否为可重试的临时故障（网络中断、服务端错误），用于决定是否显示重试入口 */
  get isRetryable(): boolean {
    return this.status === 0 || this.status >= 500
  }
}

interface ErrorDetail {
  code?: unknown
  message?: unknown
  existing?: unknown
  fields?: unknown
}

function pickString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value ? value : fallback
}

function parseExisting(value: unknown): DuplicateInfo | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const id = Number(item.id)
  if (!Number.isFinite(id)) return null
  return {
    id,
    code: pickString(item.code, ''),
    title: pickString(item.title, ''),
    conference: pickString(item.conference, ''),
    year: Number(item.year) || 0,
  }
}

function parseFields(value: unknown): { field: string; message: string }[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return []
    const item = entry as Record<string, unknown>
    return [{ field: pickString(item.field, ''), message: pickString(item.message, '') }]
  })
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    // 网络层失败（连接被中断）没有 HTTP 状态码，用 0 表示
    throw new ApiError(0, 'network_error', '无法连接后端服务，请确认服务已启动后重试。')
  }

  if (response.status === 204) {
    return undefined as T
  }

  const raw = await response.text()
  let payload: unknown = null
  if (raw) {
    try {
      payload = JSON.parse(raw)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    // 502/503/504 通常来自反向代理（开发环境的 Vite 代理或生产环境的 Nginx）
    // 在后端未启动时出现，直接显示 HTTP 状态码对使用者没有帮助，统一给出可操作的说明。
    if (response.status === 502 || response.status === 503 || response.status === 504) {
      throw new ApiError(
        response.status,
        'backend_unavailable',
        `无法连接后端服务（网关返回 HTTP ${response.status}），请确认后端已启动后重试。`,
      )
    }
    const detail = (payload as { detail?: ErrorDetail } | null)?.detail ?? {}
    throw new ApiError(
      response.status,
      pickString(detail.code, 'http_error'),
      pickString(detail.message, `请求失败（HTTP ${response.status}）`),
      parseExisting(detail.existing),
      parseFields(detail.fields),
    )
  }

  return payload as T
}

function toSearchParams(query: PaperQuery): string {
  const params = new URLSearchParams()
  if (query.q.trim()) params.set('q', query.q.trim())
  params.set('match', query.match)
  if (query.conferences.length) params.set('conference', query.conferences.join(','))
  if (query.yearFrom !== null) params.set('year_from', String(query.yearFrom))
  if (query.yearTo !== null) params.set('year_to', String(query.yearTo))
  if (query.keyword) params.set('keyword', query.keyword)
  if (query.topic) params.set('topic', query.topic)
  if (query.dataStatus) params.set('data_status', query.dataStatus)
  if (query.keywordStatus) params.set('keyword_status', query.keywordStatus)
  params.set('sort', query.sort)
  params.set('order', query.order)
  params.set('page', String(query.page))
  params.set('page_size', String(query.pageSize))
  return params.toString()
}

function toBody(input: PaperInput): string {
  return JSON.stringify({
    title: input.title,
    conference: input.conference,
    year: input.year,
    abstract: input.abstract || null,
    source_keywords: input.sourceKeywords,
    landing_url: input.landingUrl || null,
    pdf_url: input.pdfUrl || null,
  })
}

export async function listPapers(query: PaperQuery): Promise<PaperPage> {
  return request<PaperPage>(`${BASE}?${toSearchParams(query)}`)
}

export async function fetchPaper(id: number): Promise<PaperDetail> {
  return request<PaperDetail>(`${BASE}/${id}`)
}

export async function fetchRelatedPapers(id: number, limit = 3): Promise<PaperListItem[]> {
  const payload = await request<{ items: PaperListItem[] }>(
    `${BASE}/${id}/related?limit=${limit}`,
  )
  return payload.items
}

export async function createPaper(input: PaperInput): Promise<PaperDetail> {
  return request<PaperDetail>(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: toBody(input),
  })
}

export async function updatePaper(id: number, input: PaperInput): Promise<PaperDetail> {
  return request<PaperDetail>(`${BASE}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: toBody(input),
  })
}

export async function deletePaper(id: number): Promise<void> {
  await request<void>(`${BASE}/${id}`, { method: 'DELETE' })
}

/** 会议取值辅助：把任意字符串收敛为受支持的会议，避免把非法值带入查询参数 */
export function toConference(value: string): Conference | null {
  return value === 'CVPR' || value === 'ICCV' || value === 'ECCV' ? value : null
}
