<script setup lang="ts">
/**
 * 页面 4 · 采集与导入（对应原型 04_collect）。
 *
 * 已接入阶段 6 的真实接口，页面不含演示或占位数值：
 * - 标签页 A：POST /api/collect/lookup 按题目检索（本地优先，未命中再联网）。
 *   五种结局分别呈现：本地命中、候选、联网未找到、联网超时、来源不可用；
 *   候选必须由使用者勾选后点「确认导入」才调用 /api/collect/confirm，绝不自动选定，
 *   会议归属未知的候选要求先在表单补齐会议与年份（接口要求）。
 * - 标签页 B：GET /api/import/template 提供模板与字段说明，选择文件即调用
 *   /api/import/preview 预览（不写库），确认后才 POST /api/import/tasks 建任务；
 *   进度与计数全部取自任务明细的 pending/running/success/duplicate/failed。
 */

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { confirmCandidate, lookupPapers } from '../api/collectApi'
import {
  createImportTask,
  fetchImportTask,
  fetchImportTemplate,
  listImportTasks,
  previewImportFile,
  resumeImportTask,
  retryImportTask,
} from '../api/importApi'
import { ApiError, toConference } from '../api/paperApi'
import AppModal from '../components/AppModal.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { pushToast } from '../composables/useToast'
import {
  candidateKey,
  lookupOutcomeBadgeClass,
  lookupOutcomeLabels,
  matchScoreLabel,
  type CollectCandidate,
  type LocalPaperRef,
  type LookupOutcome,
} from '../types/collect'
import {
  formatBytes,
  isTaskTerminal,
  previewRowClass,
  previewRowStatusLabel,
  taskBadgeClass,
  taskItemBadgeClass,
  taskItemStatusLabel,
  taskProgressPercent,
  taskStatusLabel,
  type ImportPreview,
  type ImportTask,
  type ImportTaskDetail,
  type ImportTemplate,
} from '../types/import'
import {
  allConferences,
  conferenceColors,
  type Conference,
  type PaperDetail,
} from '../types/paper'

/** 轮询间隔：任务非终态时按此周期取任务详情，终态或卸载时释放定时器 */
const POLL_INTERVAL_MS = 1500
/** 年份下拉：与后端目标覆盖范围（config.TARGET_CONFERENCE_YEARS）的年份一致 */
const CONFERENCE_YEARS: number[] = [2022, 2023, 2024, 2025]
/** 模板接口未就绪时的兜底上限，与后端默认值一致，只用于本地提示 */
const DEFAULT_MAX_BYTES = 2 * 1024 * 1024

const activeTab = ref<'single' | 'batch'>('single')

// ---------------------------------------------------------------- A. 单篇采集

const singleTitle = ref('')
const singleConference = ref('')
const singleYear = ref('')
const singleError = ref('')

const lookupLoading = ref(false)
const lookupOutcome = ref<LookupOutcome | ''>('')
const lookupQuery = ref('')
const lookupSource = ref('')
const lookupMessage = ref('')
const localPapers = ref<LocalPaperRef[]>([])
const candidates = ref<CollectCandidate[]>([])
const lookupError = ref('')
const lookupErrorRetryable = ref(true)

const selectedCandidateKey = ref('')
const confirming = ref(false)
const confirmError = ref('')
const confirmedPaper = ref<PaperDetail | null>(null)

const canSubmitSingle = computed(() => singleTitle.value.trim().length > 0)

const outcomeLabel = computed(() =>
  lookupOutcome.value ? lookupOutcomeLabels[lookupOutcome.value] : '',
)
const outcomeBadgeClass = computed(() =>
  lookupOutcome.value ? lookupOutcomeBadgeClass(lookupOutcome.value) : 'badge-neutral',
)

const selectedCandidate = computed(
  () => candidates.value.find((item) => candidateKey(item) === selectedCandidateKey.value) ?? null,
)

function toYear(value: string): number | null {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function resetLookupResult(): void {
  lookupOutcome.value = ''
  lookupQuery.value = ''
  lookupSource.value = ''
  lookupMessage.value = ''
  localPapers.value = []
  candidates.value = []
  lookupError.value = ''
  selectedCandidateKey.value = ''
  confirmError.value = ''
  confirmedPaper.value = null
}

async function submitSingle(): Promise<void> {
  if (lookupLoading.value) return
  const title = singleTitle.value.trim()
  if (!title) {
    singleError.value = '请先填写论文完整题目。'
    return
  }
  if (title.length < 8) {
    singleError.value = '题目过短（少于 8 个字符），请粘贴会议论文页上的完整题目。'
    return
  }
  singleError.value = ''
  resetLookupResult()
  lookupLoading.value = true
  try {
    const response = await lookupPapers({
      title,
      conference: toConference(singleConference.value),
      year: toYear(singleYear.value),
    })
    lookupQuery.value = response.query
    lookupSource.value = response.source ?? ''
    lookupMessage.value = response.message ?? ''
    lookupOutcome.value = response.outcome
    localPapers.value = response.papers
    candidates.value = response.candidates
  } catch (error) {
    handleLookupError(error)
  } finally {
    lookupLoading.value = false
  }
}

/**
 * 采集失败分三类呈现，不能混为一谈：
 * 上游超时（504 upstream_timeout）与来源不可用（502 upstream_unavailable）是
 * 「这次没查成」，与「联网没有这条论文」是两个结论；其余错误按普通故障处理。
 */
function handleLookupError(error: unknown): void {
  if (!(error instanceof ApiError)) {
    lookupError.value = '采集失败，请稍后重试。'
    lookupErrorRetryable.value = true
    return
  }
  if (error.code === 'upstream_timeout') {
    lookupOutcome.value = 'remote_timeout'
    lookupMessage.value = error.message
    return
  }
  if (error.code === 'upstream_unavailable') {
    lookupOutcome.value = 'remote_unavailable'
    lookupMessage.value = error.message
    return
  }
  lookupError.value = error.message
  lookupErrorRetryable.value = error.isRetryable
}

/** 候选可用的会议：候选自带优先，未知时用表单里补充的值 */
function candidateConference(candidate: CollectCandidate): Conference | null {
  return candidate.conference ?? toConference(singleConference.value)
}

/**
 * 候选可用的年份。
 *
 * 会议归属未知时以表单里选的年份为准：来源给出的年份可能是预印本年而非会议年，
 * 直接采用会把论文挂到错误的会议年份上。
 */
function candidateYear(candidate: CollectCandidate): number | null {
  if (candidate.conference === null) return toYear(singleYear.value)
  return candidate.year ?? toYear(singleYear.value)
}

async function confirmSelected(): Promise<void> {
  const candidate = selectedCandidate.value
  if (!candidate || confirming.value) return
  const conference = candidateConference(candidate)
  if (!conference) {
    confirmError.value =
      '该候选的来源无法确定会议归属，请先在上方表单选择会议（必要时同时选择年份）再确认导入。'
    return
  }
  const year = candidateYear(candidate)
  if (!year) {
    confirmError.value = '请先在上方表单选择年份，采集接口要求提交明确的会议与年份。'
    return
  }
  confirmError.value = ''
  confirming.value = true
  try {
    const paper = await confirmCandidate({
      title: candidate.title,
      conference,
      year,
      source: candidate.source,
      sourceId: candidate.source_id,
      abstract: candidate.abstract ?? '',
      authors: candidate.authors,
      landingUrl: candidate.landing_url ?? '',
      pdfUrl: candidate.pdf_url ?? '',
    })
    confirmedPaper.value = paper
    pushToast(`已导入《${paper.title}》，编号 ${paper.code}，数据状态为「待复核」。`)
  } catch (error) {
    confirmError.value = error instanceof ApiError ? error.message : '确认导入失败，请稍后重试。'
  } finally {
    confirming.value = false
  }
}

// ---------------------------------------------------------------- B. 批量导入

const template = ref<ImportTemplate | null>(null)
const templateError = ref('')

const file = ref<File | null>(null)
const fileName = ref('')
const fileError = ref('')
const preview = ref<ImportPreview | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const batchConfirmOpen = ref(false)
const taskSubmitting = ref(false)

const task = ref<ImportTaskDetail | null>(null)
const taskLoading = ref(false)
const taskError = ref('')
const taskAction = ref<'' | 'retry' | 'resume'>('')
const itemFilter = ref<'' | 'success' | 'duplicate' | 'failed'>('')

const recentTasks = ref<ImportTask[]>([])
const recentLoading = ref(false)
const recentError = ref('')

const ITEM_FILTERS: { value: '' | 'success' | 'duplicate' | 'failed'; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'success', label: '成功' },
  { value: 'duplicate', label: '重复' },
  { value: 'failed', label: '失败' },
]

/** 定时器句柄：非终态任务轮询用，卸载时释放 */
let pollTimer: number | null = null

const itemFilterLabel = computed(
  () => ITEM_FILTERS.find((option) => option.value === itemFilter.value)?.label ?? '',
)

const handledCount = computed(() => {
  const current = task.value
  if (!current) return 0
  return current.success_count + current.duplicate_count + current.failed_count
})

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling(): void {
  stopPolling()
  pollTimer = window.setInterval(() => {
    void loadTaskDetail()
  }, POLL_INTERVAL_MS)
}

async function loadTemplate(): Promise<void> {
  templateError.value = ''
  try {
    template.value = await fetchImportTemplate()
  } catch (error) {
    templateError.value =
      error instanceof ApiError ? error.message : '读取导入模板失败，请稍后重试。'
  }
}

async function loadRecentTasks(): Promise<void> {
  recentLoading.value = true
  recentError.value = ''
  try {
    const data = await listImportTasks()
    recentTasks.value = data.items
  } catch (error) {
    recentError.value =
      error instanceof ApiError ? error.message : '读取最近任务失败，请稍后重试。'
  } finally {
    recentLoading.value = false
  }
}

/**
 * 刷新当前任务的进度与明细。
 *
 * 进度完全来自任务明细计数；任务进入终态时停止轮询，并在这次刷新里
 * 同步一次最近任务列表（只刷新一次，不随每次筛选重复请求）。
 */
async function loadTaskDetail(): Promise<void> {
  const current = task.value
  if (!current) return
  const wasActive = !isTaskTerminal(current.status)
  try {
    const detail = await fetchImportTask(current.id, { itemStatus: itemFilter.value })
    task.value = detail
    if (isTaskTerminal(detail.status)) {
      stopPolling()
      if (wasActive) void loadRecentTasks()
    }
  } catch (error) {
    stopPolling()
    taskError.value =
      error instanceof ApiError ? error.message : '刷新任务进度失败，请稍后重试。'
  }
}

/** 打开某个任务的详情（刷新页面后从最近任务列表恢复视图） */
async function openTask(id: number): Promise<void> {
  taskLoading.value = true
  taskError.value = ''
  try {
    const detail = await fetchImportTask(id, { itemStatus: itemFilter.value })
    task.value = detail
    if (isTaskTerminal(detail.status)) stopPolling()
    else startPolling()
  } catch (error) {
    stopPolling()
    taskError.value =
      error instanceof ApiError ? error.message : '读取任务详情失败，请稍后重试。'
  } finally {
    taskLoading.value = false
  }
}

function onPickFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0]
  if (!picked) return
  const lower = picked.name.toLowerCase()
  if (!lower.endsWith('.csv') && !lower.endsWith('.txt')) {
    fileError.value = '仅支持 CSV 与 TXT 文件。'
    input.value = ''
    return
  }
  const maxBytes = template.value?.max_bytes ?? DEFAULT_MAX_BYTES
  if (picked.size > maxBytes) {
    fileError.value = `文件大小 ${formatBytes(picked.size)} 超过 ${formatBytes(maxBytes)} 上限，请拆分后再上传。`
    input.value = ''
    return
  }
  fileError.value = ''
  previewError.value = ''
  file.value = picked
  fileName.value = picked.name
  void loadPreview(picked)
}

async function loadPreview(picked: File): Promise<void> {
  previewLoading.value = true
  previewError.value = ''
  preview.value = null
  try {
    preview.value = await previewImportFile(picked)
  } catch (error) {
    previewError.value =
      error instanceof ApiError ? error.message : '文件预览失败，请稍后重试。'
  } finally {
    previewLoading.value = false
  }
}

function clearFile(): void {
  file.value = null
  fileName.value = ''
  fileError.value = ''
  previewError.value = ''
  preview.value = null
}

async function submitBatch(): Promise<void> {
  const picked = file.value
  if (!picked || taskSubmitting.value) return
  taskSubmitting.value = true
  try {
    const created = await createImportTask(picked)
    batchConfirmOpen.value = false
    taskError.value = ''
    task.value = null
    itemFilter.value = ''
    await openTask(created.id)
    pushToast(`已创建导入任务 #${created.id}，共 ${created.total_count} 条待处理。`)
    void loadRecentTasks()
  } catch (error) {
    batchConfirmOpen.value = false
    taskError.value =
      error instanceof ApiError ? error.message : '创建导入任务失败，请稍后重试。'
  } finally {
    taskSubmitting.value = false
  }
}

async function onRetry(): Promise<void> {
  const current = task.value
  if (!current || taskAction.value) return
  taskAction.value = 'retry'
  taskError.value = ''
  try {
    await retryImportTask(current.id)
    pushToast(`已把任务 #${current.id} 的失败条目重新入队。`)
    await loadTaskDetail()
    if (task.value && !isTaskTerminal(task.value.status)) startPolling()
  } catch (error) {
    taskError.value = error instanceof ApiError ? error.message : '重试失败，请稍后重试。'
  } finally {
    taskAction.value = ''
  }
}

async function onResume(): Promise<void> {
  const current = task.value
  if (!current || taskAction.value) return
  taskAction.value = 'resume'
  taskError.value = ''
  try {
    await resumeImportTask(current.id)
    pushToast(`任务 #${current.id} 已重新开始处理未完成条目。`)
    await loadTaskDetail()
    if (task.value && !isTaskTerminal(task.value.status)) startPolling()
  } catch (error) {
    taskError.value = error instanceof ApiError ? error.message : '继续处理失败，请稍后重试。'
  } finally {
    taskAction.value = ''
  }
}

function taskKindLabel(kind: string): string {
  if (kind === 'batch') return '批量导入'
  if (kind === 'harvest') return '采集任务'
  return kind
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 后端返回 UTC 时间戳，这里按本地时区展示，避免让人误读成本地时间 */
function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  return `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

watch(itemFilter, () => {
  void loadTaskDetail()
})

onMounted(() => {
  void loadTemplate()
  void loadRecentTasks()
})

// 轮询定时器必须随组件销毁释放，否则切页后仍会持续请求
onBeforeUnmount(stopPolling)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="页面 4 / 论文采集与导入"
      title="补充论文数据"
      description="用完整题目采集单篇论文，或上传 CSV、TXT 列表批量导入。查询先查本地论文库，未命中再按会议索引或 OpenAlex 联网检索；候选必须人工确认后才入库。"
    />

    <div class="tab-row">
      <button
        type="button"
        class="tab-btn"
        :class="{ 'is-on': activeTab === 'single' }"
        @click="activeTab = 'single'"
      >
        A. 单篇采集
      </button>
      <button
        type="button"
        class="tab-btn"
        :class="{ 'is-on': activeTab === 'batch' }"
        @click="activeTab = 'batch'"
      >
        B. 批量导入
      </button>
    </div>

    <!-- ============ A. 单篇采集 ============ -->
    <section v-if="activeTab === 'single'" class="collect-grid">
      <div class="card form-card">
        <div class="card-header">
          <div>
            <h2 class="card-title">按完整题目采集</h2>
            <p class="card-subtitle">建议输入会议论文页上的完整英文题目，检索命中率更高。</p>
          </div>
        </div>
        <div class="card-body form-body">
          <div>
            <label class="field-label" for="single-title">论文完整题目</label>
            <textarea
              id="single-title"
              v-model="singleTitle"
              class="textarea"
              rows="3"
              placeholder="例如：Sapiens: Foundation for Human Vision Models"
            ></textarea>
          </div>

          <div class="two-col">
            <div>
              <label class="field-label" for="single-conf">会议（选填）</label>
              <select id="single-conf" v-model="singleConference" class="select">
                <option value="">自动判断</option>
                <option v-for="item in allConferences" :key="item" :value="item">
                  {{ item }}
                </option>
              </select>
            </div>
            <div>
              <label class="field-label" for="single-year">年份（选填）</label>
              <select id="single-year" v-model="singleYear" class="select">
                <option value="">自动判断</option>
                <option v-for="year in CONFERENCE_YEARS" :key="year" :value="year">
                  {{ year }}
                </option>
              </select>
            </div>
          </div>
          <p class="field-hint">
            填了会议与年份时，联网检索直接查该会议年份的索引，能确定会议归属并取到摘要；
            留空时按题目在 OpenAlex 检索，候选可能无法归属会议，需要在候选区补齐。
          </p>

          <p v-if="singleError" class="field-error" role="alert">{{ singleError }}</p>

          <button
            type="button"
            class="btn btn-primary btn-block"
            :disabled="lookupLoading || !canSubmitSingle"
            @click="submitSingle"
          >
            {{ lookupLoading ? '检索中…' : '开始采集' }}
          </button>

          <p class="notice notice-info">
            采集只写入确认过的记录：本地已命中时不会重复入库；联网候选由你逐条核对后确认，
            确认后的论文数据状态为「待复核」，并立即进入关键词处理。
          </p>
        </div>
      </div>

      <div class="card result-card">
        <!-- 确认导入成功：直接给出详情页入口 -->
        <div v-if="confirmedPaper" class="confirm-panel">
          <div class="confirm-head">
            <span class="badge badge-ok">已入库</span>
            <span class="confirm-code">{{ confirmedPaper.code }}</span>
            <StatusBadge :display="confirmedPaper.display_status" />
          </div>
          <p class="confirm-title">{{ confirmedPaper.title }}</p>
          <p class="confirm-meta">
            {{ confirmedPaper.conference }} {{ confirmedPaper.year }}
            <span v-if="confirmedPaper.code_note"> · {{ confirmedPaper.code_note }}</span>
          </p>
          <RouterLink
            class="btn btn-primary btn-sm confirm-link"
            :to="{ name: 'paper-detail', params: { id: confirmedPaper.id } }"
          >
            查看论文详情
          </RouterLink>
        </div>

        <div v-if="lookupLoading" class="loading-panel" role="status">
          正在检索…先查本地论文库，未命中再联网查找。
        </div>

        <!-- 请求本身失败（参数、网络或服务端故障），与「没有结果」分开 -->
        <div v-else-if="lookupError" class="error-panel" role="alert">
          <p class="error-title">采集请求失败</p>
          <p class="error-desc">{{ lookupError }}</p>
          <div class="error-actions">
            <button
              v-if="lookupErrorRetryable"
              type="button"
              class="btn btn-secondary"
              @click="submitSingle"
            >
              重试
            </button>
            <span v-else class="error-note">请调整题目或会议年份后重新采集。</span>
          </div>
        </div>

        <!-- 本地命中 -->
        <div v-else-if="lookupOutcome === 'local_hit'" class="result-body">
          <div class="result-head">
            <span class="badge" :class="outcomeBadgeClass">{{ outcomeLabel }}</span>
            <span class="result-query">查询：{{ lookupQuery }}</span>
          </div>
          <ul class="hit-list">
            <li v-for="paper in localPapers" :key="paper.id" class="hit-item">
              <RouterLink
                class="paper-title line-2"
                :to="{ name: 'paper-detail', params: { id: paper.id } }"
              >
                {{ paper.title }}
              </RouterLink>
              <p class="hit-meta">
                <span class="conf-cell">
                  <span
                    class="conf-dot"
                    :style="{ background: conferenceColors[paper.conference] }"
                    aria-hidden="true"
                  ></span>
                  {{ paper.conference }}
                </span>
                <span>{{ paper.year }}</span>
                <span class="mono">{{ paper.code }}</span>
              </p>
            </li>
          </ul>
          <p class="result-foot">
            本地已有记录，不再重复采集；如需补齐摘要、关键词或原文链接，可进入详情页编辑。
          </p>
        </div>

        <!-- 联网候选：必须人工勾选并确认 -->
        <div v-else-if="lookupOutcome === 'remote_candidates'" class="result-body">
          <div class="result-head">
            <span class="badge" :class="outcomeBadgeClass">{{ outcomeLabel }}</span>
            <span class="result-query">
              查询：{{ lookupQuery }}
              <template v-if="lookupSource"> · 来源：{{ lookupSource }}</template>
            </span>
          </div>
          <p class="result-hint">
            共 {{ candidates.length }} 条候选，需要逐条核对后手动勾选一条再确认导入。
            会议为「未知」的候选，请先在左侧表单补齐会议与年份。
          </p>

          <ul class="candidate-list">
            <li
              v-for="candidate in candidates"
              :key="candidateKey(candidate)"
              class="candidate-item"
            >
              <label class="candidate-main">
                <input
                  v-model="selectedCandidateKey"
                  type="radio"
                  name="collect-candidate"
                  :value="candidateKey(candidate)"
                />
                <span class="candidate-body">
                  <span class="candidate-title">{{ candidate.title }}</span>
                  <span class="candidate-meta">
                    <span class="conf-cell">
                      <span
                        v-if="candidate.conference"
                        class="conf-dot"
                        :style="{ background: conferenceColors[candidate.conference] }"
                        aria-hidden="true"
                      ></span>
                      {{ candidate.conference ?? '会议未知' }}
                    </span>
                    <span>{{ candidate.year ?? '年份未知' }}</span>
                    <span>来源：{{ candidate.source }}</span>
                    <span v-if="candidate.venue">{{ candidate.venue }}</span>
                    <span>相似度 {{ matchScoreLabel(candidate.match_score) }}</span>
                  </span>
                  <span class="candidate-tags">
                    <span
                      class="badge"
                      :class="candidate.abstract_missing ? 'badge-warn' : 'badge-ok'"
                    >
                      {{ candidate.abstract_missing ? '摘要缺失' : '含摘要' }}
                    </span>
                    <span v-if="!candidate.conference" class="badge badge-danger">
                      需补充会议与年份
                    </span>
                    <span v-if="candidate.already_exists" class="badge badge-warn">
                      已在库中：{{ candidate.existing_code ?? '编号未知' }}
                    </span>
                  </span>
                  <span v-for="note in candidate.notes" :key="note" class="candidate-note">
                    · {{ note }}
                  </span>
                  <span
                    v-if="candidate.already_exists && candidate.existing_code"
                    class="candidate-note"
                  >
                    已在库中的记录可先按编号查询：
                    <RouterLink
                      class="link-inline"
                      :to="{ name: 'papers', query: { query: candidate.existing_code } }"
                    >
                      {{ candidate.existing_code }}
                    </RouterLink>
                    ；确认导入只会补齐来源与缺失字段，不会新增重复记录。
                  </span>
                </span>
              </label>
            </li>
          </ul>

          <div class="candidate-actions">
            <span class="candidate-picked">
              <template v-if="selectedCandidate">
                已选择：{{ selectedCandidate.title }}
              </template>
              <template v-else>尚未选择候选，页面不会自动替你选定</template>
            </span>
            <button
              type="button"
              class="btn btn-primary"
              :disabled="!selectedCandidate || confirming"
              @click="confirmSelected"
            >
              {{ confirming ? '导入中…' : '确认导入' }}
            </button>
          </div>
          <p v-if="confirmError" class="field-error" role="alert">{{ confirmError }}</p>
        </div>

        <!-- 联网没有找到：不是故障 -->
        <div v-else-if="lookupOutcome === 'remote_empty'" class="result-body">
          <div class="result-head">
            <span class="badge" :class="outcomeBadgeClass">{{ outcomeLabel }}</span>
            <span class="result-query">
              查询：{{ lookupQuery }}
              <template v-if="lookupSource"> · 来源：{{ lookupSource }}</template>
            </span>
          </div>
          <p class="result-desc">
            在线来源没有返回匹配的论文，本地论文库也没有命中。可以改用会议论文页上的完整题目
            （含副标题）重新采集，或在表单中指定会议与年份后按会议索引精确匹配。
          </p>
        </div>

        <!-- 联网超时：本地查询已完成，失败的是联网这一步 -->
        <div v-else-if="lookupOutcome === 'remote_timeout'" class="result-body" role="alert">
          <div class="result-head">
            <span class="badge" :class="outcomeBadgeClass">{{ outcomeLabel }}</span>
            <span class="result-query">查询：{{ lookupQuery }}</span>
          </div>
          <p class="result-desc">{{ lookupMessage || '在线检索超过等待上限，未能取得结果。' }}</p>
          <p class="result-foot">
            这是联网检索超时，不是「没有这篇论文」：本地论文库的查询已经完成且没有命中。
            稍后重试即可，或在表单中指定会议与年份改用会议索引查询。
          </p>
          <button type="button" class="btn btn-secondary" @click="submitSingle">重试</button>
        </div>

        <div v-else-if="lookupOutcome === 'remote_unavailable'" class="result-body" role="alert">
          <div class="result-head">
            <span class="badge" :class="outcomeBadgeClass">{{ outcomeLabel }}</span>
            <span class="result-query">查询：{{ lookupQuery }}</span>
          </div>
          <p class="result-desc">{{ lookupMessage || '在线来源当前不可用，未能取得结果。' }}</p>
          <p class="result-foot">
            本次未能访问在线来源（来源方故障或网络不通），不代表论文不存在。
            可以稍后重试，或改用已有的会议索引年份查询。
          </p>
          <button type="button" class="btn btn-secondary" @click="submitSingle">重试</button>
        </div>

        <EmptyState
          v-else
          title="尚未开始采集"
          description="输入完整题目后点击「开始采集」。本地命中会直接给出论文详情入口；未命中时列出联网候选，由你核对会议年份、摘要完整性与是否已在库中后再决定是否导入。"
          boxed
        />
      </div>
    </section>

    <!-- ============ B. 批量导入 ============ -->
    <section v-else class="batch-stack">
      <div class="batch-grid">
        <div class="card">
          <div class="card-header">
            <div>
              <h2 class="card-title">上传论文列表文件</h2>
              <p class="card-subtitle">
                支持 CSV 与 TXT；单次不超过 {{ template?.max_rows ?? 500 }} 行、{{
                  template ? formatBytes(template.max_bytes) : '2 MB'
                }}。
              </p>
            </div>
          </div>
          <div class="card-body">
            <div class="drop-zone">
              <p class="drop-title">选择文件后立即解析预览，预览阶段不会写入数据库</p>
              <label class="btn btn-secondary" for="batch-file">选择文件</label>
              <input
                id="batch-file"
                class="visually-hidden"
                type="file"
                accept=".csv,.txt,text/csv,text/plain"
                @change="onPickFile"
              />
            </div>

            <div v-if="fileName" class="file-state">
              <span class="file-name">{{ fileName }}</span>
              <button type="button" class="link-action" @click="clearFile">移除</button>
            </div>

            <p v-if="fileError" class="field-error" role="alert">{{ fileError }}</p>
            <p v-if="previewLoading" class="file-note" role="status">正在解析并预览文件…</p>
            <p v-else-if="previewError" class="field-error" role="alert">{{ previewError }}</p>
            <p v-else-if="preview" class="file-note">
              已预览 {{ preview.file_name }}（{{ preview.file_format.toUpperCase() }}），
              其中 {{ preview.importable_count }} 行可导入。
            </p>

            <p class="notice notice-info batch-notice">
              预览只做解析与校验，不写数据库；预览结果里的重复是「同一文件内重复」，
              与论文库中已存在的记录在创建任务时才比对。
            </p>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div>
              <h2 class="card-title">模板示例与字段说明</h2>
              <p class="card-subtitle">按模板整理后再上传，可显著减少失败条目。</p>
            </div>
            <span v-if="template" class="tag">
              {{ template.max_rows }} 行 / {{ formatBytes(template.max_bytes) }}
            </span>
          </div>
          <div class="card-body template-body">
            <p v-if="templateError" class="field-error" role="alert">
              {{ templateError }}
              <button type="button" class="link-action" @click="loadTemplate">重试</button>
            </p>

            <template v-if="template">
              <div>
                <div class="template-head">
                  <span class="template-label">TXT 模板（每行一个论文题目）</span>
                  <span class="tag">.txt</span>
                </div>
                <pre class="template-code">{{ template.txt_template }}</pre>
              </div>

              <div>
                <div class="template-head">
                  <span class="template-label">CSV 模板（含 title、conference、year 三列）</span>
                  <span class="tag">.csv</span>
                </div>
                <pre class="template-code">{{ template.csv_template }}</pre>
              </div>

              <table class="field-table">
                <thead>
                  <tr>
                    <th>字段</th>
                    <th>是否必填</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="note in template.field_notes" :key="note.name">
                    <td class="mono">{{ note.name }}</td>
                    <td>{{ note.required }}</td>
                    <td>{{ note.note }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>
        </div>
      </div>

      <!-- 预览结果 -->
      <section v-if="preview" class="card">
        <div class="card-header">
          <div>
            <h2 class="card-title">预览结果</h2>
            <p class="card-subtitle">
              逐行校验结果，未写库；校验不过的行会在创建任务时跳过。
            </p>
          </div>
          <span class="badge badge-primary">可导入 {{ preview.importable_count }} 行</span>
        </div>
        <div class="card-body">
          <div class="stat-grid stat-grid-5">
            <StatCard label="总行数" :value="String(preview.total_lines)" hint="文件内的数据行，不含表头" />
            <StatCard label="有效" :value="String(preview.valid_count)" hint="通过校验，可提交导入" />
            <StatCard label="无效" :value="String(preview.invalid_count)" hint="校验不过，导入时跳过" />
            <StatCard
              label="文件内重复"
              :value="String(preview.duplicate_in_file_count)"
              hint="同一文件内重复，只处理第一次出现"
            />
            <StatCard label="空行" :value="String(preview.blank_count)" hint="空行不计入校验" />
          </div>

          <p
            v-for="warning in preview.warnings"
            :key="warning"
            class="notice notice-warn preview-warning"
          >
            {{ warning }}
          </p>

          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th class="col-line">行号</th>
                  <th>题目</th>
                  <th class="col-conf">会议</th>
                  <th class="col-year">年份</th>
                  <th class="col-status">状态</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in preview.rows"
                  :key="row.line_no"
                  :class="previewRowClass(row.status)"
                >
                  <td class="mono">{{ row.line_no }}</td>
                  <td>{{ row.title }}</td>
                  <td>{{ row.conference ?? '—' }}</td>
                  <td>{{ row.year ?? '—' }}</td>
                  <td>{{ previewRowStatusLabel(row.status) }}</td>
                  <td class="cell-message">{{ row.message ?? '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="preview-actions">
            <span class="preview-note">
              确认后将把 {{ preview.importable_count }} 行创建为导入任务，在后台逐条匹配会议索引并写入。
            </span>
            <button
              type="button"
              class="btn btn-primary"
              :disabled="!file || preview.importable_count === 0"
              @click="batchConfirmOpen = true"
            >
              确认导入
            </button>
          </div>
        </div>
      </section>

      <!-- 处理进度与逐项结果 -->
      <section class="card">
        <div class="card-header">
          <div>
            <h2 class="card-title">处理进度与逐项结果</h2>
            <p class="card-subtitle">
              计数来自任务明细的实际状态，不做估算；非终态时页面每 1.5 秒自动刷新。
            </p>
          </div>
          <span v-if="task" class="badge" :class="taskBadgeClass(task.status)">
            {{ taskStatusLabel(task.status) }}
          </span>
        </div>
        <div class="card-body">
          <p v-if="taskError" class="form-error" role="alert">{{ taskError }}</p>

          <p v-if="taskLoading" class="loading-panel" role="status">正在读取任务详情…</p>

          <template v-else-if="task">
            <div class="progress-head">
              <span class="progress-title">
                任务 #{{ task.id }} · {{ taskKindLabel(task.kind) }}
                <template v-if="task.file_name"> · {{ task.file_name }}</template>
              </span>
              <span class="progress-pct">{{ taskProgressPercent(task) }}%</span>
            </div>
            <div class="progress-track">
              <div
                class="progress-fill"
                :style="{ width: `${taskProgressPercent(task)}%` }"
              ></div>
            </div>
            <p class="progress-note">
              已处理 {{ handledCount }} / {{ task.total_count }} 条（成功 {{ task.success_count }}、
              重复 {{ task.duplicate_count }}、失败 {{ task.failed_count }}；待处理
              {{ task.pending_count }}、处理中 {{ task.running_count }}）。
              <template v-if="!isTaskTerminal(task.status)">
                任务尚未结束，进度会继续刷新。
              </template>
            </p>
            <p v-if="task.message" class="task-message">{{ task.message }}</p>

            <div class="stat-grid">
              <StatCard
                label="总条目数"
                :value="String(task.total_count)"
                hint="任务已写入的行数，不含被跳过的无效行"
              />
              <StatCard
                label="导入成功"
                :value="String(task.success_count)"
                hint="已在论文库中新增记录"
              />
              <StatCard
                label="导入失败"
                :value="String(task.failed_count)"
                hint="失败条目可重试，重试仍走去重"
              />
              <StatCard
                label="重复条目"
                :value="String(task.duplicate_count)"
                hint="已存在，说明里给出论文编号"
              />
            </div>

            <div class="task-actions">
              <button
                v-if="task.failed_count > 0"
                type="button"
                class="btn btn-secondary"
                :disabled="taskAction !== ''"
                @click="onRetry"
              >
                {{ taskAction === 'retry' ? '提交中…' : '重试失败条目' }}
              </button>
              <button
                v-if="task.resumable"
                type="button"
                class="btn btn-primary"
                :disabled="taskAction !== ''"
                @click="onResume"
              >
                {{ taskAction === 'resume' ? '提交中…' : '继续处理' }}
              </button>
              <span v-if="!task.failed_count && !task.resumable" class="task-actions-note">
                没有失败或未完成的条目。
              </span>
            </div>

            <div class="items-head">
              <div class="filter-chips">
                <button
                  v-for="option in ITEM_FILTERS"
                  :key="option.value"
                  type="button"
                  class="chip-toggle"
                  :class="{ 'is-on': itemFilter === option.value }"
                  @click="itemFilter = option.value"
                >
                  {{ option.label }}
                </button>
              </div>
              <span class="items-count">
                当前显示 {{ task.items.length }} 条<template v-if="itemFilter">（已筛选：{{
                  itemFilterLabel
                }}）</template>，任务共 {{ task.total_count }} 条
              </span>
            </div>

            <div v-if="task.items.length" class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th class="col-line">行号</th>
                    <th>题目</th>
                    <th class="col-conf">会议</th>
                    <th class="col-year">年份</th>
                    <th class="col-status">状态</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in task.items" :key="item.line_no">
                    <td class="mono">{{ item.line_no }}</td>
                    <td>
                      <RouterLink
                        v-if="item.status === 'success' && item.paper_id"
                        class="paper-title"
                        :to="{ name: 'paper-detail', params: { id: item.paper_id } }"
                      >
                        {{ item.input_title }}
                      </RouterLink>
                      <RouterLink
                        v-else-if="item.status === 'duplicate' && item.duplicate_of_paper_id"
                        class="paper-title"
                        :to="{ name: 'paper-detail', params: { id: item.duplicate_of_paper_id } }"
                      >
                        {{ item.input_title }}
                      </RouterLink>
                      <span v-else>{{ item.input_title }}</span>
                    </td>
                    <td>{{ item.input_conference ?? '—' }}</td>
                    <td>{{ item.input_year ?? '—' }}</td>
                    <td>
                      <span class="badge" :class="taskItemBadgeClass(item.status)">
                        {{ taskItemStatusLabel(item.status) }}
                      </span>
                    </td>
                    <td class="cell-message">{{ item.message ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <EmptyState
              v-else
              title="没有符合条件的明细"
              description="可以切换筛选条件查看其他状态的条目。"
            />
          </template>

          <EmptyState
            v-else
            title="尚未创建导入任务"
            description="在上方选择 CSV 或 TXT 文件并确认导入后，这里会显示任务进度与逐项结果；进度来自任务明细计数，不使用模拟进度条。"
          />
        </div>
      </section>

      <!-- 最近任务：刷新页面后从这里恢复视图 -->
      <section class="card">
        <div class="card-header">
          <div>
            <h2 class="card-title">最近任务</h2>
            <p class="card-subtitle">来自 GET /api/import/tasks，刷新页面后仍可查看并继续处理。</p>
          </div>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="recentLoading"
            @click="loadRecentTasks"
          >
            刷新列表
          </button>
        </div>
        <div class="card-body">
          <p v-if="recentError" class="form-error" role="alert">{{ recentError }}</p>
          <p v-else-if="recentLoading" class="loading-panel" role="status">正在加载任务列表…</p>

          <div v-else-if="recentTasks.length" class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th class="col-line">任务</th>
                  <th class="col-kind">类型</th>
                  <th>文件</th>
                  <th class="col-status">状态</th>
                  <th class="col-num">总条目</th>
                  <th class="col-num">成功</th>
                  <th class="col-num">重复</th>
                  <th class="col-num">失败</th>
                  <th class="col-time">创建时间</th>
                  <th class="col-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in recentTasks"
                  :key="item.id"
                  :class="{ 'is-current': task !== null && task.id === item.id }"
                >
                  <td class="mono">#{{ item.id }}</td>
                  <td>{{ taskKindLabel(item.kind) }}</td>
                  <td>{{ item.file_name ?? '—' }}</td>
                  <td>
                    <span class="badge" :class="taskBadgeClass(item.status)">
                      {{ taskStatusLabel(item.status) }}
                    </span>
                  </td>
                  <td>{{ item.total_count }}</td>
                  <td>{{ item.success_count }}</td>
                  <td>{{ item.duplicate_count }}</td>
                  <td>{{ item.failed_count }}</td>
                  <td class="mono">{{ formatTime(item.created_at) }}</td>
                  <td>
                    <button type="button" class="link-action" @click="openTask(item.id)">查看</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <EmptyState
            v-else
            title="还没有导入任务"
            description="选择文件并确认导入后，任务会出现在这里。"
          />
        </div>
      </section>
    </section>

    <AppModal
      :open="batchConfirmOpen"
      title="确认导入这份文件？"
      width="520px"
      :close-on-backdrop="!taskSubmitting"
      @close="batchConfirmOpen = false"
    >
      <template v-if="preview">
        <p class="modal-file mono">{{ preview.file_name }}</p>
        <p class="modal-line">
          将提交 {{ preview.importable_count }} 行创建导入任务，后台逐条匹配会议索引并写入论文库；
          任务创建后可随时查看进度，中断了也能继续处理。
        </p>
        <p class="modal-line">
          校验不过 {{ preview.invalid_count }} 行（不提交）、文件内重复
          {{ preview.duplicate_in_file_count }} 行（只处理第一次出现）、空行
          {{ preview.blank_count }} 行。
        </p>
        <p class="modal-line">
          任务只提交「可导入」的行；已经存在于论文库的记录会在处理时标记为重复，
          不会重复入库。
        </p>
      </template>
      <template #footer>
        <button
          type="button"
          class="btn btn-secondary"
          :disabled="taskSubmitting"
          @click="batchConfirmOpen = false"
        >
          取消
        </button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="taskSubmitting"
          @click="submitBatch"
        >
          {{ taskSubmitting ? '提交中…' : '确认导入' }}
        </button>
      </template>
    </AppModal>
  </div>
</template>

<style scoped>
.tab-row {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.tab-btn {
  padding: 10px 20px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-subtle);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.tab-btn.is-on {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.collect-grid {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: 24px;
  align-items: start;
}

.form-card .form-body {
  display: grid;
  gap: 16px;
}

.two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.field-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--color-text-faint);
  line-height: 1.7;
}

.result-card {
  padding: 20px 24px;
}

.result-body {
  display: grid;
  gap: 12px;
}

.result-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.result-query {
  font-size: 12px;
  color: var(--color-text-subtle);
  word-break: break-all;
}

.result-hint,
.result-desc,
.result-foot {
  font-size: 12px;
  line-height: 1.8;
  color: var(--color-text-muted);
}

.result-foot {
  color: var(--color-text-subtle);
}

.hit-list {
  display: grid;
  gap: 12px;
}

.hit-item {
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.hit-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.conf-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}

.paper-title {
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-text);
}

.paper-title:hover {
  color: var(--color-primary);
  text-decoration: underline;
}

.candidate-list {
  display: grid;
  gap: 12px;
}

.candidate-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.candidate-item:hover {
  border-color: var(--color-primary-soft-strong);
}

.candidate-main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
}

.candidate-body {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.candidate-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-strong);
}

.candidate-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.candidate-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.candidate-note {
  font-size: 11px;
  line-height: 1.7;
  color: var(--color-warn-text);
}

.link-inline {
  color: var(--color-primary);
}

.link-inline:hover {
  text-decoration: underline;
}

.candidate-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-soft);
}

.candidate-picked {
  font-size: 12px;
  color: var(--color-text-subtle);
}

.confirm-panel {
  display: grid;
  gap: 8px;
  margin-bottom: 16px;
  padding: 16px;
  border: 1px solid var(--color-ok-border);
  border-radius: var(--radius-md);
  background: var(--color-ok-bg);
}

.confirm-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.confirm-code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-ok-text);
}

.confirm-title {
  font-size: 14px;
  color: var(--color-text-strong);
}

.confirm-meta {
  font-size: 12px;
  color: var(--color-ok-text);
}

.confirm-link {
  justify-self: flex-start;
  width: auto;
}

.loading-panel {
  padding: 48px 24px;
  text-align: center;
  font-size: 14px;
  color: var(--color-text-subtle);
}

.error-panel {
  padding: 16px 20px;
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-md);
  background: var(--color-danger-bg);
}

.error-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-danger-text);
}

.error-desc,
.error-note {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-danger-text);
}

.error-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

.batch-stack {
  display: grid;
  gap: 24px;
}

.batch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  align-items: start;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 24px;
  border: 2px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-surface-muted);
  text-align: center;
}

.drop-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-muted);
}

.file-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.file-name {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-text-muted);
  word-break: break-all;
}

.file-note {
  margin-top: 12px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.batch-notice {
  margin-top: 16px;
}

.template-body {
  display: grid;
  gap: 20px;
}

.template-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.template-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.template-code {
  margin: 0;
  padding: 12px 16px;
  overflow-x: auto;
  border-radius: var(--radius-md);
  background: var(--color-text-strong);
  color: #e2e8f0;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre;
}

.field-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.field-table th {
  padding-bottom: 8px;
  color: var(--color-text-subtle);
  font-weight: 600;
  text-align: left;
}

.field-table td {
  padding: 8px 0;
  border-top: 1px solid var(--color-border-soft);
  color: var(--color-text-muted);
}

.field-table .mono {
  font-family: var(--font-mono);
  color: var(--color-text);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-grid-5 {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.preview-warning {
  margin-top: 12px;
}

.table-wrap {
  margin-top: 16px;
  overflow-x: auto;
}

.table-wrap .data-table {
  min-width: 900px;
}

.col-line {
  width: 70px;
}

.col-conf {
  width: 90px;
}

.col-year {
  width: 80px;
}

.col-status {
  width: 120px;
}

.col-kind {
  width: 100px;
}

.col-num {
  width: 80px;
}

.col-time {
  width: 140px;
}

.col-actions {
  width: 80px;
}

.cell-message {
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.preview-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-soft);
}

.preview-note {
  font-size: 12px;
  color: var(--color-text-subtle);
}

.progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.progress-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.progress-pct {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--color-text-muted);
}

.progress-track {
  height: 8px;
  margin: 12px 0 8px;
  border-radius: 999px;
  background: var(--color-inactive);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--color-primary);
  transition: width 0.3s ease;
}

.progress-note,
.task-message {
  font-size: 12px;
  line-height: 1.8;
  color: var(--color-text-muted);
}

.task-message {
  margin-top: 4px;
  font-family: var(--font-mono);
  color: var(--color-text-subtle);
}

.task-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin: 20px 0;
}

.task-actions-note {
  font-size: 12px;
  color: var(--color-text-faint);
}

.items-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-soft);
}

.filter-chips {
  display: flex;
  gap: 8px;
}

.filter-chips .chip-toggle {
  padding: 6px 12px;
  font-size: 12px;
}

.items-count {
  font-size: 12px;
  color: var(--color-text-subtle);
}

.data-table tr.is-current {
  background: var(--color-primary-soft);
}

.modal-file {
  font-size: 12px;
  color: var(--color-text-strong);
  word-break: break-all;
}

.modal-line {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--color-text-muted);
}

@media (max-width: 1200px) {
  .collect-grid,
  .batch-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .stat-grid,
  .stat-grid-5 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .two-col,
  .stat-grid,
  .stat-grid-5 {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
