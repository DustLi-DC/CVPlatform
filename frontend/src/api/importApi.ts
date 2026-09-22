/**
 * 批量导入与任务接口。
 *
 * 上传一律用 FormData，字段名固定为 file（与后端 multipart 定义一致）。
 * 预览只解析不写库；确认后才创建任务，进度与计数由 GET /api/import/tasks/{id}
 * 提供，前端不估算进度。
 */
import type {
  ImportPreview,
  ImportTask,
  ImportTaskDetail,
  ImportTaskList,
  ImportTemplate,
} from '../types/import'
import { apiRequest } from './paperApi'

const BASE = '/api/import'

/** 明细一次性取满一页（后端上限 200），避免默认 50 条截断后计数对不上明细 */
const ITEM_PAGE_SIZE = 200

/** 上传的文件字段名固定为 file，集中在这里，页面不自己拼 FormData */
function fileBody(file: File): FormData {
  const body = new FormData()
  body.append('file', file)
  return body
}

export async function fetchImportTemplate(): Promise<ImportTemplate> {
  return apiRequest<ImportTemplate>(`${BASE}/template`)
}

/** 解析并预览文件，不写数据库 */
export async function previewImportFile(file: File): Promise<ImportPreview> {
  return apiRequest<ImportPreview>(`${BASE}/preview`, {
    method: 'POST',
    body: fileBody(file),
  })
}

/** 创建批量导入任务；返回 202 与任务本身，处理在后台进行 */
export async function createImportTask(file: File): Promise<ImportTask> {
  return apiRequest<ImportTask>(`${BASE}/tasks`, {
    method: 'POST',
    body: fileBody(file),
  })
}

export async function listImportTasks(limit = 20): Promise<ImportTaskList> {
  return apiRequest<ImportTaskList>(`${BASE}/tasks?limit=${limit}`)
}

export interface TaskDetailQuery {
  /** 按明细状态筛选；空表示不过滤 */
  itemStatus?: string
  page?: number
  pageSize?: number
}

export async function fetchImportTask(
  id: number,
  query: TaskDetailQuery = {},
): Promise<ImportTaskDetail> {
  const params = new URLSearchParams()
  if (query.itemStatus) params.set('item_status', query.itemStatus)
  params.set('page', String(query.page ?? 1))
  params.set('page_size', String(query.pageSize ?? ITEM_PAGE_SIZE))
  return apiRequest<ImportTaskDetail>(`${BASE}/tasks/${id}?${params.toString()}`)
}

/** 重试失败条目；没有失败条目时后端返回 409 task_not_resumable */
export async function retryImportTask(id: number): Promise<ImportTask> {
  return apiRequest<ImportTask>(`${BASE}/tasks/${id}/retry`, { method: 'POST' })
}

/** 继续处理未完成条目；没有待处理条目时后端返回 409 task_not_resumable */
export async function resumeImportTask(id: number): Promise<ImportTask> {
  return apiRequest<ImportTask>(`${BASE}/tasks/${id}/resume`, { method: 'POST' })
}
