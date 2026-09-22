<script setup lang="ts">
/**
 * 页面 3 · 论文列表管理（对应原型 03_papers）。
 *
 * 已接入阶段 3 的真实接口：列表、精确/模糊搜索、会议与年份区间筛选、关键词筛选、
 * 排序、分页、新增/编辑/删除（含确认）。
 *
 * 状态覆盖：加载中、接口失败（带重试）、空库、无结果、以及「本地未命中」面板
 * （联网检索在阶段 5 接入，这里只保留接入位置与禁用原因，不模拟检索过程）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { ApiError, deletePaper, fetchPaper, listPapers } from '../api/paperApi'
import AppModal from '../components/AppModal.vue'
import EmptyState from '../components/EmptyState.vue'
import KeywordTag from '../components/KeywordTag.vue'
import PageHeader from '../components/PageHeader.vue'
import Pagination from '../components/Pagination.vue'
import PaperFormModal from '../components/PaperFormModal.vue'
import StatusBadge from '../components/StatusBadge.vue'
import YearRangeSelect from '../components/YearRangeSelect.vue'
import { pushToast } from '../composables/useToast'
import { demoYears } from '../demo/coverage'
import {
  allConferences,
  conferenceColors,
  keywordBadgeFor,
  type Conference,
  type MatchMode,
  type PaperDetail,
  type PaperListItem,
  type PaperPage,
  type PaperQuery,
  type PaperSortField,
  type SortOrder,
} from '../types/paper'

const route = useRoute()
const router = useRouter()

const PAGE_SIZE = 8

const query = ref('')
const matchMode = ref<MatchMode>('fuzzy')
const selectedConferences = ref<Conference[]>([])
const yearFrom = ref<number | null>(null)
const yearTo = ref<number | null>(null)
const keywordFilter = ref('')
/** 主题筛选（统计页跳转时带过来；普通检索为空） */
const topicFilter = ref('')
/** 主题展示名，仅用于条件标签显示（筛选仍用 slug） */
const topicLabel = ref('')
/** 是否来自统计页跳转：为 true 时后端强制应用统计口径约束 */
const fromStats = ref(false)
const sortField = ref<PaperSortField>('code')
const sortOrder = ref<SortOrder>('asc')
const page = ref(1)

/** 提交查询后才生效的语句，仅切换筛选不会触发检索（与原型一致） */
const submittedQuery = ref('')

const pageData = ref<PaperPage | null>(null)
const loading = ref(false)
const loadError = ref('')
const loadErrorRetryable = ref(true)

const formOpen = ref(false)
const editingPaper = ref<PaperDetail | null>(null)
const deletingPaper = ref<PaperListItem | null>(null)
const deleteSubmitting = ref(false)

const items = computed(() => pageData.value?.items ?? [])
const total = computed(() => pageData.value?.total ?? 0)
const pages = computed(() => pageData.value?.pages ?? 1)

/** 完全没有任何筛选与查询条件，用于区分「空库」与「无结果」 */
const hasAnyCondition = computed(
  () =>
    Boolean(submittedQuery.value) ||
    selectedConferences.value.length > 0 ||
    yearFrom.value !== null ||
    yearTo.value !== null ||
    Boolean(keywordFilter.value) ||
    Boolean(topicFilter.value),
)

/** 本地未命中：提交过查询但没有任何结果，此时给出联网检索入口的位置 */
const localMiss = computed(
  () => Boolean(submittedQuery.value) && total.value === 0 && !loading.value && !loadError.value,
)

const activeFilters = computed(() => {
  const chips: { key: string; label: string }[] = []
  if (submittedQuery.value) chips.push({ key: 'query', label: `查询：${submittedQuery.value}` })
  chips.push({ key: 'mode', label: `匹配：${matchMode.value === 'exact' ? '精确' : '模糊'}` })
  if (selectedConferences.value.length) {
    chips.push({ key: 'conf', label: `会议：${selectedConferences.value.join(' · ')}` })
  }
  if (yearFrom.value !== null || yearTo.value !== null) {
    chips.push({
      key: 'year',
      label: `年份：${yearFrom.value ?? '不限'}—${yearTo.value ?? '不限'}`,
    })
  }
  if (keywordFilter.value) chips.push({ key: 'keyword', label: `关键词：${keywordFilter.value}` })
  if (topicFilter.value) {
    chips.push({ key: 'topic', label: `主题：${topicLabel.value || topicFilter.value}` })
  }
  if (fromStats.value) {
    // 统计页跳转时列表与统计必须同口径，这一点要在界面上说清
    chips.push({ key: 'stats', label: '统计口径：系统关键词 · 当前规则版本 · 分析集合' })
  }
  return chips
})

function buildQuery(): PaperQuery {
  return {
    q: submittedQuery.value,
    match: matchMode.value,
    conferences: selectedConferences.value,
    yearFrom: yearFrom.value,
    yearTo: yearTo.value,
    keyword: keywordFilter.value,
    topic: topicFilter.value,
    dataStatus: '',
    keywordStatus: '',
    fromStats: fromStats.value,
    sort: sortField.value,
    order: sortOrder.value,
    page: page.value,
    pageSize: PAGE_SIZE,
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const data = await listPapers(buildQuery())
    pageData.value = data
    // 服务端会把越界页码收敛到最后一页，这里同步过来，避免地址栏与页面不一致
    if (data.page !== page.value) page.value = data.page
  } catch (error) {
    pageData.value = null
    if (error instanceof ApiError) {
      loadError.value = error.message
      loadErrorRetryable.value = error.isRetryable
    } else {
      loadError.value = '加载论文列表失败，请稍后重试。'
      loadErrorRetryable.value = true
    }
  } finally {
    loading.value = false
  }
}

function clearFilter(key: string): void {
  if (key === 'query') {
    query.value = ''
    submittedQuery.value = ''
  }
  if (key === 'mode') matchMode.value = 'fuzzy'
  if (key === 'conf') selectedConferences.value = []
  if (key === 'year') {
    yearFrom.value = null
    yearTo.value = null
  }
  if (key === 'keyword') keywordFilter.value = ''
  if (key === 'topic') {
    topicFilter.value = ''
    topicLabel.value = ''
  }
  if (key === 'stats') fromStats.value = false
  page.value = 1
}

function runSearch(): void {
  submittedQuery.value = query.value
  page.value = 1
}

function resetAll(): void {
  query.value = ''
  submittedQuery.value = ''
  matchMode.value = 'fuzzy'
  selectedConferences.value = []
  yearFrom.value = null
  yearTo.value = null
  keywordFilter.value = ''
  topicFilter.value = ''
  topicLabel.value = ''
  fromStats.value = false
  sortField.value = 'code'
  sortOrder.value = 'asc'
  page.value = 1
}

function openCreate(): void {
  editingPaper.value = null
  formOpen.value = true
}

async function openEdit(paper: PaperListItem): Promise<void> {
  // 编辑需要摘要与作者关键词，列表项不含这些字段，按 id 重新取详情
  try {
    editingPaper.value = await fetchPaper(paper.id)
    formOpen.value = true
  } catch (error) {
    pushToast(
      error instanceof ApiError ? error.message : '读取论文详情失败，请稍后重试。',
      'warning',
    )
  }
}

function onSaved(): void {
  page.value = 1
  // 新增后清空查询，让新记录可见（与原型新增分支的行为一致）；编辑时保留当前查询
  if (!editingPaper.value) {
    query.value = ''
    submittedQuery.value = ''
  }
  void load()
}

async function confirmDelete(): Promise<void> {
  const target = deletingPaper.value
  if (!target || deleteSubmitting.value) return

  deleteSubmitting.value = true
  try {
    await deletePaper(target.id)
    deletingPaper.value = null
    // 删掉当前页最后一条时回退一页，避免停在空页上
    if (items.value.length === 1 && page.value > 1) page.value -= 1
    await load()
    const shortTitle = target.title.length > 18 ? `${target.title.slice(0, 18)}…` : target.title
    pushToast(`已删除《${shortTitle}》。`)
  } catch (error) {
    pushToast(
      error instanceof ApiError ? error.message : '删除失败，请稍后重试。',
      'warning',
    )
  } finally {
    deleteSubmitting.value = false
  }
}

function onKeywordClick(name: string): void {
  keywordFilter.value = name
  page.value = 1
}

// 条件或页码变化即重新加载
watch(
  [
    submittedQuery,
    matchMode,
    selectedConferences,
    yearFrom,
    yearTo,
    keywordFilter,
    sortField,
    sortOrder,
    page,
  ],
  () => {
    void load()
  },
)

/**
 * 把地址栏条件同步到本地状态。
 *
 * 只在值确实不同时赋值：否则 URL 写回与状态同步会互相触发，产生重复请求。
 */
function applyRouteQuery(params: typeof route.query): void {
  const kw = typeof params.kw === 'string' ? params.kw : ''
  if (kw !== keywordFilter.value) keywordFilter.value = kw

  const confRaw = typeof params.conf === 'string' ? params.conf : ''
  const parsed = confRaw
    .split(',')
    .filter((item): item is Conference => (allConferences as string[]).includes(item))
  if (parsed.join(',') !== selectedConferences.value.join(',')) selectedConferences.value = parsed

  const from = Number(params.year_from)
  const nextFrom = Number.isFinite(from) && from > 0 ? from : null
  if (nextFrom !== yearFrom.value) yearFrom.value = nextFrom

  const to = Number(params.year_to)
  const nextTo = Number.isFinite(to) && to > 0 ? to : null
  if (nextTo !== yearTo.value) yearTo.value = nextTo

  const topic = typeof params.topic === 'string' ? params.topic : ''
  if (topic !== topicFilter.value) topicFilter.value = topic
  const topicName = typeof params.topic_name === 'string' ? params.topic_name : ''
  if (topicName !== topicLabel.value) topicLabel.value = topicName

  const stats = params.from_stats === 'true'
  if (stats !== fromStats.value) fromStats.value = stats

  const q = typeof params.query === 'string' ? params.query : ''
  if (q !== submittedQuery.value) {
    query.value = q
    submittedQuery.value = q
  }

  const pageParam = Number(params.page)
  const nextPage = Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1
  if (nextPage !== page.value) page.value = nextPage
}

// 首次进入：先用地址栏条件初始化状态（此时 watcher 尚未建立，不会触发请求），
// 再由 onMounted 发起唯一一次列表请求。
applyRouteQuery(route.query)

// 浏览器前进/后退或外部跳转带着新条件回来时同步状态；状态变化由上面的 watcher 触发加载
watch(() => route.query, applyRouteQuery)

// 把当前条件与页码写回地址栏，使详情页返回、刷新与分享都能还原同一视图
watch(
  [submittedQuery, selectedConferences, yearFrom, yearTo, keywordFilter, topicFilter, fromStats, page],
  () => {
  const next: Record<string, string> = {}
  if (submittedQuery.value) next.query = submittedQuery.value
  if (selectedConferences.value.length) next.conf = selectedConferences.value.join(',')
  if (yearFrom.value !== null) next.year_from = String(yearFrom.value)
  if (yearTo.value !== null) next.year_to = String(yearTo.value)
  if (keywordFilter.value) next.kw = keywordFilter.value
  if (topicFilter.value) next.topic = topicFilter.value
  if (topicLabel.value) next.topic_name = topicLabel.value
  if (fromStats.value) next.from_stats = 'true'
  if (page.value > 1) next.page = String(page.value)

  const current = route.query
  const same =
    current.query === next.query &&
    current.conf === next.conf &&
    current.year_from === next.year_from &&
    current.year_to === next.year_to &&
    current.kw === next.kw &&
    current.topic === next.topic &&
    current.topic_name === next.topic_name &&
    (current.from_stats === 'true') === fromStats.value &&
    current.page === next.page
  if (!same) void router.replace({ query: next })
  },
)

onMounted(() => {
  void load()
})

</script>

<template>
  <div>
    <PageHeader
      eyebrow="页面 3 / 论文列表管理"
      title="论文管理"
      description="集中查询已采集的论文。支持按题目、编号、关键词搜索；本地论文库没有匹配结果时，可以按当前查询语句联网查找并导入。"
    >
      <template #aside>
        <button type="button" class="btn btn-secondary" :disabled="loading" @click="load">
          刷新
        </button>
        <button type="button" class="btn btn-primary" @click="openCreate">新增论文</button>
        <RouterLink class="btn btn-secondary" to="/collect">批量导入</RouterLink>
      </template>
    </PageHeader>

    <section class="card search-card">
      <div class="search-row">
        <label class="visually-hidden" for="paper-search">查询论文</label>
        <input
          id="paper-search"
          v-model="query"
          class="input search-input"
          type="search"
          placeholder="输入论文题目、编号或关键词，例如：Segment Anything / ICCV-2023-0064 / 语义分割"
          @keydown.enter="runSearch"
        />
        <button type="button" class="btn btn-primary" @click="runSearch">查询</button>
        <button type="button" class="btn btn-secondary" @click="resetAll">清空</button>
      </div>

      <div class="filter-row">
        <fieldset class="mode-field">
          <legend class="field-label">匹配方式</legend>
          <div class="mode-options">
            <label class="mode-option">
              <input v-model="matchMode" name="match-mode" type="radio" value="fuzzy" />模糊匹配
            </label>
            <label class="mode-option">
              <input v-model="matchMode" name="match-mode" type="radio" value="exact" />精确匹配
            </label>
          </div>
        </fieldset>

        <div>
          <span class="field-label">会议</span>
          <div class="conf-checks">
            <label v-for="conference in allConferences" :key="conference" class="mode-option">
              <input v-model="selectedConferences" type="checkbox" :value="conference" />{{
                conference
              }}
            </label>
          </div>
        </div>

        <YearRangeSelect
          v-model:year-from="yearFrom"
          v-model:year-to="yearTo"
          :years="demoYears"
          label="年份区间"
          unlimited
        />

        <div>
          <label class="field-label" for="kw-filter">关键词（精确匹配）</label>
          <input
            id="kw-filter"
            v-model="keywordFilter"
            class="input kw-input"
            type="text"
            placeholder="例如：目标检测"
            @keydown.enter="page = 1"
          />
          <p class="field-hint">
            按关键词精确匹配。可选词表将在阶段 7 由统计接口提供，当前不做固定下拉，
            避免列出数据中并不存在的词。
          </p>
        </div>

        <div>
          <span class="field-label">排序</span>
          <div class="sort-controls">
            <label class="visually-hidden" for="sort-field">排序字段</label>
            <select id="sort-field" v-model="sortField" class="select">
              <option value="code">编号</option>
              <option value="title">题目</option>
              <option value="year">年份</option>
              <option value="conference">会议</option>
            </select>
            <label class="visually-hidden" for="sort-order">排序方向</label>
            <select id="sort-order" v-model="sortOrder" class="select">
              <option value="asc">升序</option>
              <option value="desc">降序</option>
            </select>
          </div>
        </div>
      </div>
    </section>

    <div class="result-bar">
      <div class="chip-row">
        <template v-if="activeFilters.length">
          <span v-for="chip in activeFilters" :key="chip.key" class="filter-chip">
            {{ chip.label }}
            <button
              type="button"
              class="chip-x"
              :aria-label="`清除筛选：${chip.label}`"
              @click="clearFilter(chip.key)"
            >
              ×
            </button>
          </span>
        </template>
        <span v-else class="filter-empty">未设置筛选条件，显示全部论文</span>
      </div>
      <div class="result-count">
        <template v-if="loading">加载中…</template>
        <template v-else-if="loadError">—</template>
        <template v-else>共 <strong>{{ total }}</strong> 条结果</template>
      </div>
    </div>

    <!-- 接口失败：区分可重试与不可重试，给出明确原因 -->
    <section v-if="loadError" class="card error-panel" role="alert">
      <p class="error-title">论文列表加载失败</p>
      <p class="error-desc">{{ loadError }}</p>
      <div class="error-actions">
        <button v-if="loadErrorRetryable" type="button" class="btn btn-primary" @click="load">
          重试
        </button>
        <button v-else type="button" class="btn btn-secondary" @click="resetAll">
          清空查询条件
        </button>
      </div>
    </section>

    <!-- 本地未命中：预留联网检索的接入位置 -->
    <section v-else-if="localMiss" class="local-miss">
      <div class="miss-main">
        <p class="miss-title">本地论文库没有匹配结果</p>
        <p class="miss-desc">
          查询语句：<strong>{{ submittedQuery }}</strong
          >。可以按这条查询语句联网查找会议公开页面，找到后再决定是否导入本地论文库。
        </p>
      </div>
      <div class="miss-actions">
        <button type="button" class="btn btn-primary" disabled>联网查找</button>
        <span class="miss-note">联网检索与候选导入将在阶段 5 接入，本阶段不模拟检索过程。</span>
      </div>
    </section>

    <!-- 有查询但无结果时，由上面的「本地未命中」面板承担提示，不再重复显示通用空状态 -->
    <section v-if="!localMiss" class="card table-card">
      <div v-if="loading" class="loading-panel" role="status">正在加载论文列表…</div>

      <table v-else-if="items.length" class="data-table">
        <thead>
          <tr>
            <th class="col-code">编号</th>
            <th>题目</th>
            <th class="col-conf">会议</th>
            <th class="col-year">年份</th>
            <th class="col-keywords">关键词</th>
            <th class="col-status">数据状态</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="paper in items" :key="paper.id">
            <td class="cell-code">{{ paper.code }}</td>
            <td>
              <RouterLink
                class="paper-title line-2"
                :to="{ name: 'paper-detail', params: { id: paper.id }, query: route.query }"
                :title="paper.title"
              >
                {{ paper.title }}
              </RouterLink>
              <p v-if="paper.code_scope_mismatch" class="code-note">{{ paper.code_note }}</p>
            </td>
            <td>
              <span class="conf-cell">
                <span
                  class="conf-dot"
                  :style="{ background: conferenceColors[paper.conference] }"
                  aria-hidden="true"
                ></span>
                {{ paper.conference }}
              </span>
            </td>
            <td class="cell-year">{{ paper.year }}</td>
            <td>
              <div class="keyword-cell">
                <template v-if="paper.keywords.length">
                  <KeywordTag
                    v-for="keyword in paper.keywords"
                    :key="`${paper.id}-${keyword.origin}-${keyword.name}`"
                    :name="keyword.name"
                    :origin="keyword.origin"
                    :topic="keyword.topic"
                    @click="onKeywordClick(keyword.name)"
                  />
                </template>
                <span v-else class="keyword-empty">关键词待补充</span>
              </div>
            </td>
            <td>
              <StatusBadge :display="paper.display_status" :keyword="keywordBadgeFor(paper)" />
            </td>
            <td>
              <div class="row-actions">
                <button type="button" class="link-action" @click="openEdit(paper)">编辑</button>
                <button
                  type="button"
                  class="link-action link-action-danger"
                  @click="deletingPaper = paper"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <EmptyState
        v-else-if="!hasAnyCondition"
        title="论文库还没有记录"
        description="可以通过新增论文手工录入，或到「采集与导入」用完整题目采集、批量导入列表。"
      >
        <button type="button" class="btn btn-primary" @click="openCreate">新增论文</button>
        <RouterLink class="btn btn-secondary" to="/collect">去采集与导入</RouterLink>
      </EmptyState>

      <EmptyState
        v-else
        title="当前条件下没有论文"
        description="可以调整查询与筛选条件，或清空条件后浏览全部论文。"
      >
        <button type="button" class="btn btn-secondary" @click="resetAll">清空条件</button>
      </EmptyState>

      <Pagination
        v-if="!loading && items.length"
        v-model:page="page"
        :pages="pages"
        :total="total"
        :page-size-hint="`每页 ${PAGE_SIZE} 条`"
      />
    </section>

    <p class="table-footnote">
      列表数据来自后端接口 <code>/api/papers</code>，与会话内的数据库一致；本页不含演示数据。
    </p>

    <PaperFormModal
      :open="formOpen"
      :paper="editingPaper"
      @close="formOpen = false"
      @saved="onSaved"
    />

    <AppModal
      :open="Boolean(deletingPaper)"
      title="确认删除这篇论文？"
      width="460px"
      :close-on-backdrop="!deleteSubmitting"
      @close="deletingPaper = null"
    >
      <template v-if="deletingPaper">
        <p class="delete-title">{{ deletingPaper.title }}</p>
        <p class="delete-code">{{ deletingPaper.code }}</p>
        <p class="delete-note">
          删除后该论文将从论文库移除，关联的关键词与来源记录一并清理，关键词统计会在下次刷新时重新计算。
        </p>
      </template>
      <template #footer>
        <button
          type="button"
          class="btn btn-secondary"
          :disabled="deleteSubmitting"
          @click="deletingPaper = null"
        >
          取消
        </button>
        <button
          type="button"
          class="btn btn-danger"
          :disabled="deleteSubmitting"
          @click="confirmDelete"
        >
          {{ deleteSubmitting ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </AppModal>
  </div>
</template>

<style scoped>
.search-card {
  margin-bottom: 20px;
  padding: 20px 24px;
}

.search-row {
  display: flex;
  gap: 12px;
}

.search-input {
  flex: 1;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 20px 32px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-soft);
}

.mode-field {
  margin: 0;
  padding: 0;
  border: 0;
}

.mode-options,
.conf-checks {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-top: 4px;
}

.mode-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  cursor: pointer;
}

.sort-controls {
  display: flex;
  gap: 8px;
}

.sort-controls .select {
  width: auto;
  min-width: 84px;
}

.kw-input {
  width: 100%;
  min-width: 180px;
}

.result-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  font-size: 12px;
  color: var(--color-text-muted);
}

.chip-x {
  padding: 0;
  border: 0;
  background: none;
  color: var(--color-text-faint);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.chip-x:hover {
  color: var(--color-text-strong);
}

.filter-empty {
  font-size: 12px;
  color: var(--color-text-subtle);
}

.result-count {
  font-size: 14px;
  color: var(--color-text-subtle);
}

.error-panel {
  margin-bottom: 20px;
  padding: 20px 24px;
}

.error-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-danger-text);
}

.error-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-danger-text);
}

.error-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.local-miss {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
  padding: 20px 24px;
  border: 1px solid var(--color-warn-border);
  border-radius: var(--radius-lg);
  background: var(--color-warn-bg);
}

.miss-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-warn-text);
}

.miss-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-warn-text);
}

.miss-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  flex: 0 0 auto;
}

.miss-note {
  font-size: 11px;
  color: var(--color-warn-text);
}

.table-card {
  overflow: hidden;
}

.loading-panel {
  padding: 64px 24px;
  text-align: center;
  font-size: 14px;
  color: var(--color-text-subtle);
}

.col-code {
  width: 130px;
}

.col-conf {
  width: 90px;
}

.col-year {
  width: 80px;
}

.col-keywords {
  width: 240px;
}

.col-status {
  width: 150px;
}

.col-actions {
  width: 120px;
}

.cell-code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-text-subtle);
}

.paper-title {
  max-width: 420px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-text);
}

.paper-title:hover {
  color: var(--color-primary);
  text-decoration: underline;
}

.code-note {
  margin-top: 4px;
  font-size: 11px;
  color: var(--color-warn-text);
}

.conf-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.cell-year {
  font-size: 12px;
  color: var(--color-text-muted);
}

.keyword-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.keyword-empty {
  font-size: 11px;
  color: var(--color-text-faint);
}

.row-actions {
  display: flex;
  gap: 12px;
}

.table-footnote {
  margin-top: 12px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.table-footnote code {
  font-family: var(--font-mono);
}

.delete-title {
  font-size: 14px;
  color: var(--color-text);
}

.delete-code {
  margin-top: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text-subtle);
}

.delete-note {
  margin-top: 12px;
  font-size: 11px;
  line-height: 1.7;
  color: var(--color-text-subtle);
}

/* 窄窗口：表格允许横向滚动，不压缩列宽导致文字重叠 */
@media (max-width: 1200px) {
  .table-card {
    overflow-x: auto;
  }

  .table-card :deep(.data-table) {
    min-width: 960px;
  }
}

@media (max-width: 900px) {
  .search-row {
    flex-wrap: wrap;
  }

  .error-actions {
    flex-wrap: wrap;
  }

  .local-miss {
    flex-direction: column;
  }

  .miss-actions {
    align-items: flex-start;
  }
}
</style>
