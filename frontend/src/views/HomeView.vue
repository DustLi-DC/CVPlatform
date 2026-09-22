<script setup lang="ts">
/**
 * 页面 1 · 热门方向总览（对应原型 01_home）。
 *
 * 数据来源：`GET /api/stats/{summary,top,graph}`（阶段 8 接入，页面数值全部来自数据库，
 * 不再使用演示数据）。统计口径固定为「分析集合去重论文数」：
 *
 * - 分母只含「会议年份有效、标题可用、关键词已按当前规则版本处理完成」的论文，
 *   处理成功但关键词为空仍计入；待处理/失败/旧版本单列在 excluded 中，页面必须显示；
 * - 「未归类」不参与榜单排序（它恒等于分母），但数量与占比在图例处说明；
 * - 缺失与零严格区分：没有样本显示「—」，有样本但计数为 0 显示 0。
 */
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import ChartContainer from '../components/ChartContainer.vue'
import ConferenceChips from '../components/ConferenceChips.vue'
import PageHeader from '../components/PageHeader.vue'
import PaperDrawer from '../components/PaperDrawer.vue'
import RankBarList, { type RankItem } from '../components/RankBarList.vue'
import StatCard from '../components/StatCard.vue'
import YearRangeSelect from '../components/YearRangeSelect.vue'
import { fetchGraph, fetchSummary, fetchTop } from '../api/statsApi'
import { useAvailableYears } from '../composables/useAvailableYears'
import { ApiError, listPapers } from '../api/paperApi'
import type { PaperListItem } from '../types/paper'
import { allConferences, type Conference } from '../types/paper'
import {
  formatShare,
  groupColor,
  groupLabel,
  legendForGroups,
  type GraphEdge,
  type GraphNode,
  type StatsGraph,
  type StatsSummary,
  type StatsTop,
} from '../types/stats'

// 图谱依赖 ECharts（约 200 kB gzip）：按需异步加载，使论文管理、采集等页面
// 的首屏不携带图表库；加载期间由 ChartContainer 的占位内容兜住布局
const KeywordGraph = defineAsyncComponent(() => import('../components/KeywordGraph.vue'))

const route = useRoute()
const router = useRouter()

/** 图谱节点规模控制：默认 40 个节点、最小共现 2 篇（与设计文档一致） */
const NODE_LIMITS = [20, 40, 60, 100]
const MIN_EDGES = [1, 2, 3, 5]

const conferences = ref<Conference[]>([...allConferences])
const yearFrom = ref<number | null>(null)
const yearTo = ref<number | null>(null)
const nodeLimit = ref(40)
const minEdge = ref(2)

const summary = ref<StatsSummary | null>(null)
const top = ref<StatsTop | null>(null)
const graph = ref<StatsGraph | null>(null)

const loading = ref(true)
const loadError = ref('')
const loadErrorRetryable = ref(true)

/** 抽屉：当前查看的主题（key 为统计标识，name 为展示名） */
const activeKey = ref('')
const activeName = ref('')
const drawerPapers = ref<PaperListItem[]>([])
const drawerPapersLoading = ref(false)
const drawerPapersError = ref('')

/** 请求序号：快速切换筛选时，旧响应不得覆盖新结果 */
let requestToken = 0

/**
 * 年份选项必须与当前筛选**无关**：早先这里用的是 `summary.years`，而它是按筛选范围算出来的，
 * 于是把结束年份选到 2023 之后，接口只返回 2020—2023，下拉里就再也选不到 2024—2026。
 * 现在取自 `/api/stats/coverage`（平台实际覆盖的年份 + 目标年份，与筛选无关）。
 */
const { years: availableYears, load: loadAvailableYears } = useAvailableYears()

/** 数据更新时间：后端给的是 UTC ISO 串，这里只做可读化展示，不改数值 */
const updatedAtText = computed(() => {
  const raw = summary.value?.data_updated_at
  if (!raw) return '暂无同步记录'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
})
const hasData = computed(() => summary.value?.has_data ?? false)

const rankItems = computed<RankItem[]>(() =>
  (top.value?.items ?? []).map((item) => ({
    key: item.key,
    label: item.name,
    count: item.count,
    color: groupColor(item.group),
    active: item.key === activeKey.value,
  })),
)

const scopeText = computed(() => ({
  conferenceLabel: conferences.value.length ? conferences.value.join(' · ') : '未选择会议',
  rangeLabel:
    yearFrom.value === null && yearTo.value === null
      ? '全部年份'
      : `${yearFrom.value ?? '最早'}—${yearTo.value ?? '最新'}`,
}))

/** 被排除在分母之外的论文数：必须在页面上如实单列 */
const excludedNote = computed(() => {
  const excluded = summary.value?.excluded
  if (!excluded) return ''
  const parts: string[] = []
  if (excluded.pending) parts.push(`${excluded.pending} 篇待处理`)
  if (excluded.failed) parts.push(`${excluded.failed} 篇关键词处理失败`)
  if (excluded.stale) parts.push(`${excluded.stale} 篇待重算（规则版本已更新）`)
  if (excluded.invalid_title) parts.push(`${excluded.invalid_title} 篇标题不可用`)
  return parts.length ? `另有 ${parts.join('、')}，未计入分母。` : ''
})

/** 覆盖说明：样本性质、未覆盖的目标组合，以及未归类关键词的规模 */
const coverageNote = computed(() => {
  const coverage = summary.value?.coverage
  if (!coverage) return ''
  const parts: string[] = []
  const kinds = coverage.coverage_kinds
  const fullYears = (coverage.full_coverage_years ?? []).length
  if (fullYears) {
    parts.push(
      `其中 ${fullYears} 个会议年份是 2020 年及以后的完整论文集，` +
        '这些年份的占比即该届录用论文中的比例。',
    )
  }
  if (kinds && kinds.sampled + kinds.partial > 0 && coverage.sample_limit_per_conference_year) {
    parts.push(
      `另有 ${kinds.sampled + kinds.partial} 个会议年份为抽样` +
        `（每组合最多 ${coverage.sample_limit_per_conference_year} 篇），只反映样本内的相对热度。`,
    )
  }
  if (coverage.missing_conference_years.length) {
    const missing = coverage.missing_conference_years
      .map((item) => `${item.conference} ${item.year}`)
      .join('、')
    parts.push(`以下目标会议年份尚未采集到数据：${missing}。`)
  }
  const unmapped = summary.value?.unmapped
  if (unmapped?.applies) {
    parts.push(
      `还有 ${unmapped.keyword_total} 个关键词未归入任何主题（涉及 ${unmapped.paper_count} 篇论文），` +
        '它们不计入下面的主题榜单，但已如实保留在关键词中。',
    )
  }
  return parts.join('')
})

const graphLegend = computed(() => legendForGroups((graph.value?.nodes ?? []).map((n) => n.group)))

const graphRangeNote = computed(() => {
  const data = graph.value
  if (!data) return ''
  const parts = [
    `当前展示 ${data.nodes.length} / ${data.node_total} 个主题节点`,
    `连线仅保留共现论文数 ≥ ${data.min_edge} 的 ${data.edges.length} 条`,
  ]
  if (data.truncated) {
    parts.push('节点已按相关论文数截断，可在上方调整节点上限')
  }
  return parts.join('；') + '。'
})

const graphNodes = computed<GraphNode[]>(() => graph.value?.nodes ?? [])
const graphEdges = computed<GraphEdge[]>(() => graph.value?.edges ?? [])

const activeCount = computed(() => {
  const item = top.value?.items.find((entry) => entry.key === activeKey.value)
  if (item) return item.count
  const node = graph.value?.nodes.find((entry) => entry.key === activeKey.value)
  return node?.count ?? 0
})

const activeShare = computed(() => {
  const denominator = top.value?.denominator ?? summary.value?.denominator ?? 0
  if (denominator <= 0) return null
  return (activeCount.value / denominator) * 100
})

const drawerCoTopics = computed(() => {
  if (!activeKey.value) return []
  return (graph.value?.edges ?? [])
    .filter((edge) => edge.source === activeKey.value || edge.target === activeKey.value)
    .map((edge) => ({
      name: edge.source === activeKey.value ? edge.target_name : edge.source_name,
      weight: edge.weight,
    }))
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 4)
})

const drawerQuery = computed(() => {
  const query: Record<string, string> = { from_stats: 'true' }
  if (activeKey.value) query.topic = activeKey.value
  if (activeName.value) query.topic_name = activeName.value
  if (conferences.value.length) query.conf = conferences.value.join(',')
  if (yearFrom.value !== null) query.year_from = String(yearFrom.value)
  if (yearTo.value !== null) query.year_to = String(yearTo.value)
  return query
})

const trendEntry = computed(() => {
  const hottest = summary.value?.hottest
  if (!hottest) return null
  return { name: hottest.name, count: hottest.count, share: hottest.share }
})

function currentScope() {
  return {
    conferences: [...conferences.value],
    yearFrom: yearFrom.value,
    yearTo: yearTo.value,
  }
}

async function load(): Promise<void> {
  const token = ++requestToken
  loading.value = true
  loadError.value = ''
  try {
    const scope = currentScope()
    // 三个请求并发；任一失败即视为本页加载失败，避免出现半真半假的统计
    const [summaryData, topData, graphData] = await Promise.all([
      fetchSummary(scope),
      fetchTop(scope, { limit: 10 }),
      fetchGraph(scope, { limit: nodeLimit.value, minEdge: minEdge.value }),
    ])
    if (token !== requestToken) return // 已有更新的筛选请求，丢弃本次结果
    summary.value = summaryData
    top.value = topData
    graph.value = graphData
    // 年份区间默认对齐「平台覆盖的年份」（与筛选无关的那份），避免用筛选结果自限
    const years = availableYears.value
    if (yearFrom.value === null && yearTo.value === null && years.length) {
      yearFrom.value = years[0] ?? null
      yearTo.value = years[years.length - 1] ?? null
    }
  } catch (error) {
    if (token !== requestToken) return
    summary.value = null
    top.value = null
    graph.value = null
    if (error instanceof ApiError) {
      loadError.value = error.message
      loadErrorRetryable.value = error.isRetryable
    } else {
      // 非接口错误（例如渲染期异常）在界面上给通用文案，同时打到控制台便于排查
      console.error('加载统计数据失败：', error)
      loadError.value = '加载统计数据失败，请稍后重试。'
      loadErrorRetryable.value = true
    }
  } finally {
    if (token === requestToken) loading.value = false
  }
}

/** 抽屉里的示例论文：复用论文列表接口，并带上与统计一致的口径约束 */
async function loadDrawerPapers(): Promise<void> {
  if (!activeKey.value) return
  drawerPapersLoading.value = true
  drawerPapersError.value = ''
  try {
    const page = await listPapers({
      q: '',
      match: 'fuzzy',
      conferences: [...conferences.value],
      yearFrom: yearFrom.value,
      yearTo: yearTo.value,
      keyword: '',
      topic: activeKey.value,
      dataStatus: '',
      keywordStatus: '',
      fromStats: true,
      sort: 'year',
      order: 'desc',
      page: 1,
      pageSize: 3,
    })
    drawerPapers.value = page.items
  } catch (error) {
    drawerPapers.value = []
    drawerPapersError.value =
      error instanceof ApiError ? error.message : '加载相关论文失败，请稍后重试。'
  } finally {
    drawerPapersLoading.value = false
  }
}

function resetFilters(): void {
  conferences.value = [...allConferences]
  yearFrom.value = availableYears.value[0] ?? null
  yearTo.value = availableYears.value[availableYears.value.length - 1] ?? null
  nodeLimit.value = 40
  minEdge.value = 2
}

function openTopicDrawer(item: { key: string; name: string }): void {
  activeKey.value = item.key
  activeName.value = item.name
  void router.replace({ query: { ...route.query, kw: item.key } })
  void loadDrawerPapers()
}

function closeDrawer(): void {
  activeKey.value = ''
  activeName.value = ''
  drawerPapers.value = []
  const query = { ...route.query }
  delete query.kw
  void router.replace({ query })
}

/** 依据统计返回的榜单/图谱解析 ?kw=（支持 slug 或主题名，两者都能打开抽屉） */
function applyRouteKeyword(value: unknown): void {
  if (typeof value !== 'string' || !value) {
    if (activeKey.value) closeDrawer()
    return
  }
  const fromTop = top.value?.items.find(
    (item) => item.key === value || item.name === value,
  )
  const fromGraph = graph.value?.nodes.find(
    (node) => node.key === value || node.name === value,
  )
  const found = fromTop ?? fromGraph
  if (found) {
    openTopicDrawer(found)
  }
}

// 筛选变化即重新加载（年份与会议）；图谱规模变化只重取图谱，避免整页闪烁
watch([conferences, yearFrom, yearTo], () => {
  void load()
})
watch([nodeLimit, minEdge], () => {
  void load()
})
watch(
  () => route.query.kw,
  (value) => applyRouteKeyword(value),
)

onMounted(async () => {
  await loadAvailableYears()
  await load()
  applyRouteKeyword(route.query.kw)
})
</script>

<template>
  <div>
    <PageHeader
      variant="hero"
      eyebrow="页面 1 / 热门方向总览"
      title="计算机视觉顶会热词分析"
      description="面向刚接触计算机视觉的同学：把 CVPR、ICCV、ECCV 近几年已采集的论文题目与摘要放在一起统计，先看清哪些方向在被反复研究，再顺着热词找到值得读的论文。"
      :notice="
        summary?.coverage.sampled
          ? '本页为抽样样本统计（每会议年份约 ' +
            (summary?.coverage.sample_limit_per_conference_year ?? 0) +
            ' 篇），占比表示样本内的相对热度，不代表整届大会的录用比例。'
          : ''
      "
      :stats="[
        {
          label: '纳入论文样本',
          value: summary ? summary.total_sample.toLocaleString('zh-CN') : '—',
          hint: '篇（含待处理，分母见下）',
        },
        {
          label: '平台覆盖会议年份',
          value: summary ? String(summary.coverage.conference_years) : '—',
          hint: '个组合（与下方筛选无关）',
        },
      ]"
    />

    <section class="card filter-card">
      <div class="filter-row">
        <ConferenceChips v-model="conferences" />
        <YearRangeSelect
          v-model:year-from="yearFrom"
          v-model:year-to="yearTo"
          :years="availableYears"
        />
        <div class="filter-scope">
          <span class="field-label">当前统计范围</span>
          <p class="scope-text">
            <strong>{{ scopeText.conferenceLabel }}</strong>
            ｜ {{ scopeText.rangeLabel }} ｜ 纳入分析分母
            <strong class="scope-strong">{{ summary ? summary.denominator : '—' }}</strong>
            篇
            <span v-if="loading" class="scope-loading">· 正在加载…</span>
          </p>
        </div>
        <button type="button" class="btn btn-secondary" @click="resetFilters">重置筛选</button>
      </div>

      <p v-if="excludedNote" class="filter-notice notice notice-warn">{{ excludedNote }}</p>
      <p v-if="coverageNote" class="filter-notice filter-coverage">{{ coverageNote }}</p>
    </section>

    <p v-if="loadError" class="card load-error" role="alert">
      <span>{{ loadError }}</span>
      <button v-if="loadErrorRetryable" type="button" class="btn btn-secondary" @click="load">
        重试
      </button>
    </p>

    <section class="kpi-grid">
      <StatCard
        label="纳入分析分母"
        :value="summary ? String(summary.denominator) : '—'"
        hint="已完成关键词处理的有效论文"
      />
      <StatCard
        label="出现过的关键词"
        :value="summary ? String(summary.keyword_total) : '—'"
        :hint="
          summary
            ? `系统提取去重；未归类 ${summary.unmapped_keyword_total} 个`
            : '系统提取去重'
        "
      />
      <StatCard
        label="范围最热方向"
        :value="summary?.hottest ? summary.hottest.name : '—'"
        :hint="
          summary?.hottest
            ? `${summary.hottest.count} 篇相关论文 · 占比 ${formatShare(summary.hottest.share)}`
            : '当前范围没有可用样本'
        "
      />
      <StatCard
        label="数据更新时间"
        :value="summary?.data_updated_at ? updatedAtText.slice(5, 10) : '—'"
        :hint="updatedAtText"
      />
    </section>

    <section class="main-grid">
      <div class="card rank-card">
        <div class="card-header">
          <div>
            <h2 class="card-title">Top 10 热门研究方向</h2>
            <p class="card-subtitle">
              按当前范围内包含该方向的论文数排序（去重计数，同一篇论文只算一次）
            </p>
          </div>
          <span class="tag">单位：篇</span>
        </div>

        <RankBarList
          v-if="rankItems.length"
          :items="rankItems"
          @select="openTopicDrawer({ key: $event.key, name: $event.label })"
        />
        <p v-else-if="loading" class="rank-placeholder">正在加载统计结果…</p>
        <p v-else-if="!hasData" class="rank-placeholder">
          当前筛选范围内没有可统计的论文。可放宽年份或会议条件；若确实没有数据，
          这不是「热度为 0」，而是样本未覆盖。
        </p>
        <p v-else class="rank-placeholder">
          该范围内没有已归入主题的关键词，榜单为空。图例处可看到未归类关键词的数量。
        </p>

        <div class="rank-footer">
          <span>点击任意方向可查看相关论文</span>
          <RouterLink class="rank-link" to="/papers">进入论文管理 →</RouterLink>
        </div>
      </div>

      <ChartContainer
        title="关键词关系图谱"
        subtitle="节点为研究主题，连线表示两个主题在同一篇论文中共同出现（按去重论文数计权）"
        :legend="graphLegend"
        height="430px"
      >
        <template #tools>
          <label class="graph-control">
            <span class="field-label">节点上限</span>
            <select v-model.number="nodeLimit" class="input input-compact">
              <option v-for="limit in NODE_LIMITS" :key="limit" :value="limit">{{ limit }}</option>
            </select>
          </label>
          <label class="graph-control">
            <span class="field-label">最小共现</span>
            <select v-model.number="minEdge" class="input input-compact">
              <option v-for="edge in MIN_EDGES" :key="edge" :value="edge">{{ edge }} 篇</option>
            </select>
          </label>
        </template>

        <KeywordGraph
          v-if="graphNodes.length"
          :nodes="graphNodes"
          :edges="graphEdges"
          height="430px"
          @select="openTopicDrawer"
        />
        <div v-else class="chart-placeholder">
          <p class="chart-placeholder-title">
            {{ loading ? '正在加载图谱…' : '当前范围没有可绘制的主题关系' }}
          </p>
          <p class="chart-placeholder-note">
            {{
              loading
                ? '正在请求 /api/stats/graph'
                : '图谱需要至少两个已归入主题的关键词。可放宽筛选，或到「采集与导入」补充论文。'
            }}
          </p>
        </div>

        <template #footnote>
          <span>
            <strong>节点</strong>：一个研究主题；<strong>节点越大</strong>，当前范围内与它相关的论文越多。
          </span>
          <span>
            <strong>连线</strong>：两个主题出现在同一篇论文中；<strong>越粗</strong>表示共现论文数越多。
          </span>
          <span class="graph-range">{{ graphRangeNote }}</span>
          <span>
            节点上限与最小共现可调；主题来自版本化主题表，未归类的关键词不参与图谱（它们不会
            与任何节点连成边）。
          </span>
        </template>
      </ChartContainer>
    </section>

    <section class="card trend-entry">
      <div class="trend-entry-main">
        <h2 class="card-title">下一步：把「现在很热」变成「怎么变热的」</h2>
        <p class="trend-entry-desc">
          进入热度走势对比，选择研究方向与会议，逐年播放各年份的热度曲线，看清某个方向是在持续升温，
          还是已经开始降温。纵轴使用各会议各自的占比（count / 该会议年份样本量），避免会议规模差异造成误读。
        </p>
        <div class="trend-entry-actions">
          <RouterLink
            class="btn btn-primary"
            :to="{
              path: '/trends',
              query: {
                kw: trendEntry ? summary?.hottest?.key : undefined,
                conf: conferences.join(','),
              },
            }"
          >
            对比热度走势
          </RouterLink>
          <RouterLink class="btn btn-secondary" to="/papers">浏览论文列表</RouterLink>
        </div>
      </div>
      <div class="trend-entry-cards">
        <RouterLink
          v-for="item in (top?.items ?? []).slice(0, 3)"
          :key="item.key"
          class="trend-entry-card"
          :to="{ path: '/trends', query: { kw: item.key } }"
        >
          <span class="trend-entry-conf">
            <span
              class="conf-dot"
              :style="{ background: groupColor(item.group) }"
              aria-hidden="true"
            ></span>
            {{ groupLabel(item.group) }}
          </span>
          <span class="trend-entry-topic">{{ item.name }}</span>
          <span class="trend-entry-hint">{{ item.count }} 篇 · 占比 {{ formatShare(item.share) }}</span>
        </RouterLink>
      </div>
    </section>

    <PaperDrawer
      :open="Boolean(activeKey)"
      :topic-name="activeName"
      :count="activeCount"
      :share="activeShare"
      :co-topics="drawerCoTopics"
      :papers="drawerPapers"
      :papers-loading="drawerPapersLoading"
      :papers-error="drawerPapersError"
      :list-query="drawerQuery"
      @close="closeDrawer"
    />
  </div>
</template>

<style scoped>
.filter-card {
  margin-bottom: 24px;
  padding: 20px 24px;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 40px;
}

.filter-scope {
  flex: 1;
  min-width: 260px;
}

.scope-text {
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.scope-strong {
  color: var(--color-primary);
}

.scope-loading {
  color: var(--color-text-faint);
  font-size: 12px;
}

.filter-notice {
  margin-top: 16px;
}

.filter-coverage {
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-subtle);
}

.load-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  padding: 16px 20px;
  border-color: var(--color-danger-border, #fecaca);
  color: var(--color-danger, #b91c1c);
  font-size: 13px;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: 24px;
  align-items: start;
}

.rank-card {
  display: flex;
  flex-direction: column;
}

.rank-placeholder {
  padding: 24px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text-subtle);
}

.rank-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border-soft);
  font-size: 12px;
  color: var(--color-text-subtle);
}

.rank-link {
  color: var(--color-primary);
  font-weight: 500;
}

.rank-link:hover {
  text-decoration: underline;
}

.graph-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.input-compact {
  width: auto;
  padding: 4px 8px;
  font-size: 12px;
}

.graph-range {
  color: var(--color-text-muted);
}

.chart-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 100%;
  margin: 20px 24px;
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
  text-align: center;
  padding: 16px;
}

.chart-placeholder-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.chart-placeholder-note {
  max-width: 460px;
  font-size: 12px;
  color: var(--color-text-subtle);
  line-height: 1.7;
}

.trend-entry {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 40px;
  margin-top: 24px;
  padding: 24px 28px;
}

.trend-entry-main {
  max-width: 560px;
}

.trend-entry-desc {
  margin-top: 8px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.trend-entry-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.trend-entry-cards {
  display: flex;
  gap: 12px;
  flex: 0 0 auto;
}

.trend-entry-card {
  display: block;
  width: 168px;
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.trend-entry-card:hover {
  border-color: var(--color-conf-cvpr);
  box-shadow: var(--shadow-pop);
}

.trend-entry-conf {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.trend-entry-topic {
  display: block;
  margin-top: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.trend-entry-hint {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: var(--color-text-subtle);
}

/* 窄窗口：KPI 两列、主区单列、入口卡换行 */
@media (max-width: 1200px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .main-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 1100px) {
  .trend-entry {
    flex-direction: column;
    align-items: flex-start;
    gap: 24px;
  }

  .trend-entry-cards {
    flex-wrap: wrap;
  }
}

@media (max-width: 700px) {
  .kpi-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .filter-row {
    gap: 20px;
  }

  .filter-row > * {
    width: 100%;
  }
}
</style>
