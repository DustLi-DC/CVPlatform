/**
 * 单篇采集接口。
 *
 * 复用 src/api/paperApi.ts 的 apiRequest 与 ApiError：后端错误统一为
 * {"detail": {"code", "message"}}，采集的超时与来源不可用也用这一结构表达。
 * 这两个状态码是 504 / 502，与「网关不通」同码，因此请求时开启
 * preserveUpstreamErrors，把带回业务 code 的响应原样抛出，页面才能区分
 * 「联网超时」「来源不可用」与「查不到」。
 */
import type { ConfirmInput, ConfirmResult, LookupInput, LookupResponse } from '../types/collect'
import { apiRequest } from './paperApi'

const BASE = '/api/collect'

export async function lookupPapers(input: LookupInput): Promise<LookupResponse> {
  return apiRequest<LookupResponse>(
    `${BASE}/lookup`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: input.title,
        conference: input.conference,
        year: input.year,
      }),
    },
    { preserveUpstreamErrors: true },
  )
}

/** 确认导入候选项；会议与年份由调用方补齐后提交，服务端仍会做去重校验 */
export async function confirmCandidate(input: ConfirmInput): Promise<ConfirmResult> {
  return apiRequest<ConfirmResult>(`${BASE}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: input.title,
      conference: input.conference,
      year: input.year,
      source: input.source,
      source_id: input.sourceId,
      abstract: input.abstract || null,
      authors: input.authors,
      landing_url: input.landingUrl || null,
      pdf_url: input.pdfUrl || null,
    }),
  })
}
