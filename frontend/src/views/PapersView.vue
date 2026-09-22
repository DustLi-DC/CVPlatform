<script setup lang="ts">
/**
 * 页面 3 · 论文列表管理（对应原型 03_papers）。
 *
 * 已实现：搜索（精确/模糊）、会议与年份区间筛选、关键词筛选、已生效条件、排序、
 * 分页、新增/编辑/删除（含本地校验与去重冲突提示）、本地未命中面板。
 *
 * 尚未接入后端：数据来自内存演示库，写入提示中明确说明“仅在本页内存中生效”；
 * 联网检索在阶段 5 接入，此处只呈现状态与禁用原因，不模拟进度。
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import AppModal from '../components/AppModal.vue'
import EmptyState from '../components/EmptyState.vue'
import KeywordTag from '../components/KeywordTag.vue'
import PageHeader from '../components/PageHeader.vue'
import Pagination from '../components/Pagination.vue'
import PaperFormModal from '../components/PaperFormModal.vue'
import StatusBadge from '../components/StatusBadge.vue'
import YearRangeSelect from '../components/YearRangeSelect.vue'
import { NOT_CONNECTED_NOTICE, demoYears } from '../demo/coverage'
import { deletePaper, getPaper, paperStore, queryPapers, resetDemoPapers } from '../demo/store'
import { demoKeywordOptions } from '../demo/topics'
import { pushToast } from '../composables/useToast'
import {
  allConferences,
  conferenceColors,
  displayStatusLabels,
  keywordStatusLabels,
  type Conference,
  type MatchMode,
  type Paper,
  type PaperSortField,
  type SortOrder,
} from '../types/paper'

const route = useRoute()
const router = useRouter()

const query = ref('')
const matchMode = ref<MatchMode>('fuzzy')
const selectedConferences = ref<Conference[]>([])
const yearFrom = ref<number | null>(null)
const yearTo = ref<number | null>(null)
const keywordFilter = ref('')
const sortField = ref<PaperSortField>('code')
const sortOrder = ref<SortOrder>('asc')
const page = ref(1)
const pageSize = 8

const formOpen = ref(false)
const editingPaper = ref<Paper | null>(null)
const deletingPaper = ref<Paper | null>(null)

/** 提交查询后才生效的语句，切换筛选不会误触发联网检索（与原型一致） */
const submittedQuery = ref('')

const result = computed(() =>
  queryPapers({
    q: submittedQuery.value,
    match: matchMode.value,
    conferences: selectedConferences.value,
    yearFrom: yearFrom.value,
    yearTo: yearTo.value,
    keyword: keywordFilter.value,
    topic: '',
    page: page.value,
    pageSize,
    sort: sortField.value,
    order: sortOrder.value,
  }),
)

/** 演示库中的记录总数（与当前筛选无关），用于页脚说明 */
const totalRecords = computed(() => paperStore.papers.value.length)

/** 本地未命中：提交过查询、但当前条件（不含筛选）下没有结果 */
const localMiss = computed(
  () => Boolean(submittedQuery.value) && result.value.total === 0,
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
  return chips
})

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
  sortField.value = 'code'
  sortOrder.value = 'asc'
  page.value = 1
}

function openCreate(): void {
  editingPaper.value = null
  formOpen.value = true
}

function openEdit(paper: Paper): void {
  editingPaper.value = paper
  formOpen.value = true
}

function onSaved(): void {
  page.value = 1
  // 新增后清空查询，让新记录可见（与原型新增分支的行为一致）；编辑时保留当前查询
  if (!editingPaper.value) {
    query.value = ''
    submittedQuery.value = ''
  }
}

function confirmDelete(): void {
  const target = deletingPaper.value
  if (!target) return
  deletePaper(target.id)
  deletingPaper.value = null
  const shortTitle = target.title.length > 18 ? `${target.title.slice(0, 18)}…` : target.title
  pushToast(`已删除《${shortTitle}》。${NOT_CONNECTED_NOTICE}`, 'neutral')
}

function keywordStatusOf(paper: Paper): 'done' | 'pending' | 'running' | 'failed' | 'empty' {
  if (paper.keywordStatus === 'done' && paper.systemKeywords.length === 0) return 'empty'
  return paper.keywordStatus
}

function onKeywordClick(name: string): void {
  keywordFilter.value = name
  page.value = 1
}

function resetDemoData(): void {
  resetDemoPapers()
  resetAll()
  pushToast('已重置为初始演示数据。', 'neutral')
}

// 支持从首页/趋势页带条件进入，并完整保留年份区间
watch(
  () => route.query,
  (params) => {
    const kw = params.kw
    if (typeof kw === 'string' && kw) keywordFilter.value = kw
    const conf = params.conf
    if (typeof conf === 'string' && conf) {
      const parsed = conf.split(',').filter((item): item is Conference =>
        (allConferences as string[]).includes(item),
      )
      if (parsed.length) selectedConferences.value = parsed
    }
    const from = Number(params.year_from)
    if (Number.isFinite(from) && from > 0) yearFrom.value = from
    const to = Number(params.year_to)
    if (Number.isFinite(to) && to > 0) yearTo.value = to
    const q = params.query
    if (typeof q === 'string' && q) {
      query.value = q
      submittedQuery.value = q
    }
    page.value = 1
  },
  { immediate: true },
)

/** 详情页返回时保留条件：把当前条件写回地址栏，供返回与分享使用 */watch([selectedConferences, yearFrom, yearTo, keywordFilter, submittedQuery], () => {
  const next: Record<string, string> = {}
  if (submittedQuery.value) next.query = submittedQuery.value
  if (selectedConferences.value.length) next.conf = selectedConferences.value.join(',')
  if (yearFrom.value !== null) next.year_from = String(yearFrom.value)
  if (yearTo.value !== null) next.year_to = String(yearTo.value)
  if (keywordFilter.value) next.kw = keywordFilter.value
  const current = route.query
  const same =
    current.query === next.query &&
    current.conf === next.conf &&
    current.year_from === next.year_from &&
    current.year_to === next.year_to &&
    current.kw === next.kw
  if (!same) void router.replace({ query: next })
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
        <button type="button" class="btn btn-secondary" @click="resetDemoData">
          重置演示数据
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
              <input v-model="matchMode" type="radio" value="fuzzy" />模糊匹配
            </label>
            <label class="mode-option">
              <input v-model="matchMode" type="radio" value="exact" />精确匹配
            </label>
          </div>
        </fieldset>

        <div>
          <span class="field-label">会议</span>
          <div class="conf-checks">
            <label v-for="conference in allConferences" :key="conference" class="mode-option">
              <input
                v-model="selectedConferences"
                type="checkbox"
                :value="conference"
              />{{ conference }}
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
          <label class="field-label" for="kw-filter">关键词</label>
          <select id="kw-filter" v-model="keywordFilter" class="select">
            <option value="">全部关键词</option>
            <option v-for="name in demoKeywordOptions" :key="name" :value="name">
              {{ name }}
            </option>
          </select>
        </div>

        <div>
          <label class="field-label" for="sort-field">排序</label>
          <div class="sort-controls">
            <select id="sort-field" v-model="sortField" class="select">
              <option value="code">编号</option>
              <option value="title">题目</option>
              <option value="year">年份</option>
              <option value="conference">会议</option>
            </select>
            <select v-model="sortOrder" class="select">
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
        共 <strong>{{ result.total }}</strong> 条结果
      </div>
    </div>

    <section v-if="localMiss" class="local-miss">
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

    <section class="card table-card">
      <table v-if="result.items.length" class="data-table">
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
          <tr v-for="paper in result.items" :key="paper.id">
            <td class="cell-code">{{ paper.code }}</td>
            <td>
              <RouterLink class="paper-title line-2" :to="`/papers/${paper.id}`" :title="paper.title">
                {{ paper.title }}
              </RouterLink>
              <p v-if="paper.codeScopeMismatch" class="code-note">{{ paper.codeNote }}</p>
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
              <StatusBadge
                :display="paper.displayStatus"
                :keyword="keywordStatusOf(paper)"
              />
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
        v-else
        title="当前条件下没有论文"
        description="可以调整查询与筛选条件，或新增论文、使用批量导入补充数据。"
      />

      <Pagination
        v-if="result.items.length"
        v-model:page="page"
        :pages="result.pages"
        :total="result.total"
        :page-size-hint="`每页 ${pageSize} 条`"
      />
    </section>

    <p class="table-footnote">
      当前共 {{ totalRecords }} 条演示记录；表格数值与题目以外的字段均来自演示数据，未接入后端。
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
      @close="deletingPaper = null"
    >
      <template v-if="deletingPaper">
        <p class="delete-title">{{ deletingPaper.title }}</p>
        <p class="delete-code">{{ deletingPaper.code }}</p>
        <p class="delete-note">
          删除后该论文将从本地论文库移除，相关关键词统计会在下次刷新时重新计算。
        </p>
      </template>
      <template #footer>
        <button type="button" class="btn btn-secondary" @click="deletingPaper = null">
          取消
        </button>
        <button type="button" class="btn btn-danger" @click="confirmDelete">确认删除</button>
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
  width: 130px;
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

  .local-miss {
    flex-direction: column;
  }

  .miss-actions {
    align-items: flex-start;
  }
}
</style>
