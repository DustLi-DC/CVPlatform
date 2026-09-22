/**
 * 批量导入与采集任务的接口类型。
 *
 * 字段与 /api/import/* 的响应一一对应（snake_case），与 src/types/paper.ts 同一约定。
 * 任务状态与明细状态在后端是普通字符串（tasks.TASK_STATUSES / ITEM_STATUSES），
 * 这里用 Record<string, string> 的文案表加原样回退，未知状态直接显示原值，
 * 不把前端自己写死的一份枚举当成契约。
 */

/** 模板里的字段说明 */
export interface ImportFieldNote {
  name: string
  required: string
  note: string
}

/** GET /api/import/template 的返回：模板文本、字段说明与上限 */
export interface ImportTemplate {
  txt_template: string
  csv_template: string
  field_notes: ImportFieldNote[]
  max_rows: number
  max_bytes: number
}

/**
 * 预览行。status 由后端给出：
 * ok 可导入、invalid 校验不过、duplicate_in_file 文件内重复。
 */
export interface PreviewRow {
  line_no: number
  title: string
  conference: string | null
  year: number | null
  status: string
  /** 校验不过时的原因，原样展示给使用者 */
  message: string | null
}

export interface ImportPreview {
  file_name: string
  file_format: string
  total_lines: number
  valid_count: number
  invalid_count: number
  duplicate_in_file_count: number
  blank_count: number
  importable_count: number
  warnings: string[]
  rows: PreviewRow[]
}

/** 任务计数与状态；计数来自任务明细的实际状态，不是估算值 */
export interface ImportTask {
  id: number
  kind: string
  file_name: string | null
  file_format: string | null
  sample_stride: number | null
  sample_limit: number | null
  status: string
  message: string | null
  total_count: number
  pending_count: number
  running_count: number
  success_count: number
  duplicate_count: number
  failed_count: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  /** 是否还有未完成条目可以继续处理 */
  resumable: boolean
}

export interface ImportTaskItem {
  line_no: number
  input_title: string
  input_conference: string | null
  input_year: number | null
  /** pending / running / success / duplicate / failed */
  status: string
  paper_id: number | null
  duplicate_of_paper_id: number | null
  /** 重复或失败的原因，含已存在论文的编号，原样展示 */
  message: string | null
  attempts: number
}

export interface ImportTaskDetail extends ImportTask {
  items: ImportTaskItem[]
}

export interface ImportTaskList {
  items: ImportTask[]
  total: number
}

export const taskStatusLabels: Record<string, string> = {
  pending: '排队中',
  running: '处理中',
  interrupted: '已中断',
  success: '全部成功',
  partial: '部分成功',
  failed: '全部失败',
}

export const taskItemStatusLabels: Record<string, string> = {
  pending: '待处理',
  running: '处理中',
  success: '成功',
  duplicate: '重复',
  failed: '失败',
}

export const previewRowStatusLabels: Record<string, string> = {
  ok: '可导入',
  invalid: '校验不过',
  duplicate_in_file: '文件内重复',
}

/** 未知状态原样显示，避免把后端新增的状态折叠成「未知」而丢失信息 */
export function taskStatusLabel(status: string): string {
  return taskStatusLabels[status] ?? status
}

export function taskItemStatusLabel(status: string): string {
  return taskItemStatusLabels[status] ?? status
}

export function previewRowStatusLabel(status: string): string {
  return previewRowStatusLabels[status] ?? status
}

/** 任务状态徽标配色 */
export function taskBadgeClass(status: string): string {
  switch (status) {
    case 'success':
      return 'badge-ok'
    case 'partial':
      return 'badge-warn'
    case 'failed':
      return 'badge-danger'
    case 'running':
      return 'badge-primary'
    default:
      return 'badge-neutral'
  }
}

/** 明细状态徽标配色 */
export function taskItemBadgeClass(status: string): string {
  switch (status) {
    case 'success':
      return 'badge-ok'
    case 'duplicate':
      return 'badge-warn'
    case 'failed':
      return 'badge-danger'
    default:
      return 'badge-neutral'
  }
}

/** 预览行底色：与状态画板一致（重复用警示色、校验不过用错误色） */
export function previewRowClass(status: string): string {
  if (status === 'invalid') return 'row-failed'
  if (status === 'duplicate_in_file') return 'row-duplicate'
  return ''
}

/**
 * 终态判定。
 *
 * 与后端 tasks.NON_TERMINAL_TASK_STATUSES 一致：只有排队中、处理中、已中断
 * 属于非终态，其余（全部成功、部分成功、全部失败）不再变化，前端停止轮询。
 */
export function isTaskTerminal(status: string): boolean {
  return status !== 'pending' && status !== 'running' && status !== 'interrupted'
}

/**
 * 已处理条目占比（0—100）。
 *
 * 进度全部来自任务的明细计数：成功 + 重复 + 失败 即为已处理条目，
 * 不使用按时间估算的假进度条。
 */
export function taskProgressPercent(task: ImportTask): number {
  if (task.total_count <= 0) return 0
  const done = task.success_count + task.duplicate_count + task.failed_count
  return Math.min(100, Math.round((done / task.total_count) * 100))
}

/** 文件大小展示：按 KB / MB 给出便于核对上限 */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${Math.round((bytes / 1024 / 1024) * 10) / 10} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}
