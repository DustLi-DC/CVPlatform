<script setup lang="ts">
/**
 * 页面 2 · 热度走势对比（对应原型 02_trends）。
 *
 * 数据来源：`GET /api/stats/{summary,trend,top}`（阶段 9 接入，页面数值全部来自数据库）。
 *
 * 口径与画法：
 * - 纵轴可切换「占比（%）」与「论文数（篇）」；占比 = 该会议当年该主题论文数 ÷
 *   该会议当年纳入分析的论文总数，因此跨会议比较不受会议规模差异影响（与原型一致）；
 * - 一条曲线 = 一个会议（颜色沿用全站会议色）；同时比较多个主题时用**线型**区分主题，
 *   颜色始终表示会议，不让两种含义挤在同一个视觉通道里；
 * - 某会议某年份在库中没有任何记录时返回 null，曲线断开并画灰色区间；
 *   有样本但该主题计数为 0 的点落在 0 轴上——两者在数据与画法上都能区分；
 * - 播放只推进界面年份（每 900ms 一年，与原型一致；**原型没有倍速控件**，故不实现），
 *   曲线数据一次性取回后本地切年，年度 Top 10 视图才按年份逐年请求。
 */
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import ChartContainer from '../components/ChartContainer.vue'
import ConferenceChips from '../components/ConferenceChips.vue'
import PageHeader from '../components/PageHeader.vue'
import RankBarList, { type RankItem } from '../components/RankBarList.vue'
import YearRangeSelect from '../components/YearRangeSelect.vue'
import type { TrendLine } from '../components/TrendChart.vue'
import { ApiError } from '../api/paperApi'
import { fetchSummary, fetchTop, fetchTrend } from '../api/statsApi'
import { allConferences, conferenceColors, type Conference } from '../types/paper'
import {
  formatShare,
  groupColor,
  type StatsItem,
  type StatsSummary,
  type StatsTop,
  type StatsTrend,
  type TrendPoint,
} from '../types/stats'

// 曲线依赖 ECharts（约 160 kB gzip）：异步加载，使论文管理、采集等页面的首屏不携带图表库
const TrendChart = defineAsyncComponent(() => import('../components/TrendChart.vue'))

const route = useRoute()

/** 播放步长：与原型一致（每 900ms 前进一年） */
const PLAY_INTERVAL_MS = 900
/** 同时比较的主题上限：同一张图上超过 3 条线已难以辨读 */
const MAX_KEYS = 3
const LINE_TYPES: TrendLine['lineType'][] = ['solid', 'dashed', 'dotted']

const selectedKeys = ref<string[]>([])
const conferences = ref<Conference[]>([...allConferences])
const yearFrom = ref<number | null>(null)
const yearTo = ref<number | null>(null)
const valueMode = ref<'share' | 'count'>('share')
const currentYear = ref<number | null>(null)
const view = ref<'trend' | 'rank'>('trend')
const playing = ref(false)

const summary = ref<StatsSummary | null>(null)
const keyOptions = ref<StatsItem[]>([])
const trend = ref<StatsTrend | null>(null)
const yearRank = ref<StatsTop | null>(null)

const loading = ref(true)
const loadError = ref('')
const loadErrorRetryable = ref(true)
const rankLoading = ref(false)

let timer: number | null = null
/** 请求序号：连续切换筛选时旧响应一律丢弃 */
let trendToken = 0
let rankToken = 0

const activeYears = computed(() => {
  const years = summary.value?.years ?? []
  return years.filter(
    (year) =>
      (yearFrom.value === null || year >= yearFrom.value) &&
      (yearTo.value === null || year <= yearTo.value),
  )
})

const comparedKeys = computed(() =>
  selectedKeys.value
    .map((key) => trend.value?.series.find((series) => series.key === key) ?? null)
    .filter((series): series is NonNullable<typeof series> => series !== null),
)

const primaryKey = computed(() => comparedKeys.value[0] ?? null)

const unit = computed(() => (valueMode.value === 'share' ? '占比（%）' : '论文数（篇）'))

const LINE_LABELS = ['实线', '虚线', '点线']

/** 图例：会议色 + 主题线型（比较多个主题时）+ 无数据区间 */
const trendLegend = computed(() => [
  ...conferences.value.map((conference) => ({
    label: conference,
    color: conferenceColors[conference],
    shape: 'line' as const,
  })),
  ...(comparedKeys.value.length > 1
    ? comparedKeys.value.map((series, index) => ({
        label: `${series.name}（${LINE_LABELS[index] ?? '实线'}）`,
        color: 'var(--color-text-subtle)',
        shape: 'line' as const,
      }))
    : []),
  { label: '无数据区间', color: 'var(--color-inactive)', shape: 'block' as const },
])

const trendLines = computed<TrendLine[]>(() => {
  const data = trend.value
  if (!data) return []
  const multiple = comparedKeys.value.length > 1
  const lines: TrendLine[] = []
  comparedKeys.value.forEach((series, keyIndex) => {
    conferences.value.forEach((conference) => {
      const points = data.years.map(
        (year) =>
          series.points.find(
            (point) => point.conference === conference && point.year === year,
          ) ?? null,
      )
      lines.push({
        key: `${series.key}::${conference}`,
        label: multiple ? `${series.name} · ${conference}` : conference,
        // 颜色交给 TrendChart 在画到 canvas 前解析，本页不直接依赖图表库
        color: conferenceColors[conference],
        lineType: LINE_TYPES[keyIndex % LINE_TYPES.length] ?? 'solid',
        values: points.map((point) =>
          point === null || !point.has_data
            ? null
            : valueMode.value === 'share'
              ? point.share
              : point.count,
        ),
        // 该会议在哪些年份完全没有记录：画灰色区间，与「0 篇」区分开
        missingYears: points.flatMap((point, index) =>
          point !== null && point.reason === 'no_records_in_sample'
            ? [data.years[index] ?? 0]
            : [],
        ),
      })
    })
  })
  return lines
})

/** 侧栏表格：行 = 会议，列 = 所选主题，单元格为「计数 / 分母 = 占比」 */
const sideRows = computed(() =>
  conferences.value.map((conference) => ({
    conference,
    cells: comparedKeys.value.map((series) => ({
      key: series.key,
      point:
        series.points.find(
          (point) =>
            point.conference === conference && point.year === currentYear.value,
        ) ?? null,
    })),
  })),
)

const coverageHint = computed(() => {
  const coverage = summary.value?.coverage
  if (!coverage) return ''
  const parts: string[] = []
  const kinds = coverage.coverage_kinds
  const fullYears = (coverage.full_coverage_years ?? []).length
  if (fullYears) {
    parts.push(`其中 ${fullYears} 个会议年份为完整论文集，占比即该届录用论文中的比例。`)
  }
  if (kinds && kinds.sampled + kinds.partial > 0 && coverage.sample_limit_per_conference_year) {
    parts.push(
      `另有 ${kinds.sampled + kinds.partial} 个会议年份为抽样` +
        `（每组合最多 ${coverage.sample_limit_per_conference_year} 篇）。`,
    )
  }
  if (coverage.missing_conference_years.length) {
    parts.push(
      `尚未采集：${coverage.missing_conference_years
        .map((item) => `${item.conference} ${item.year}`)
        .join('、')}。`,
    )
  }
  return parts.join('')
})

/** 当前年份下哪些会议没有记录（对应原型趋势页的灰色区间提示） */
const missingNow = computed(() =>
  sideRows.value
    .filter((row) =>
      row.cells.some((cell) => cell.point?.reason === 'no_records_in_sample'),
    )
    .map((row) => row.conference),
)

const zeroNow = computed(() => {
  const found: Conference[] = []
  for (const row of sideRows.value) {
    for (const cell of row.cells) {
      if (cell.point?.has_data && cell.point.count === 0) found.push(row.conference)
    }
  }
  return [...new Set(found)]
})

const rankItems = computed<RankItem[]>(() =>
  (yearRank.value?.items ?? []).map((item) => ({
    key: item.key,
    label: item.name,
    count: item.count,
    color: groupColor(item.group),
    active: selectedKeys.value.includes(item.key),
  })),
)

const currentYearText = computed(() =>
  currentYear.value === null ? '—' : String(currentYear.value),
)

/** 播放按钮文案：曲终停在最后一年时显示「重播」（与原型一致） */
const playButtonText = computed(() => {
  if (playing.value) return '播放中'
  const end = yearTo.value
  if (end !== null && currentYear.value !== null && currentYear.value >= end) return '重播'
  return '播放'
})

/** 进入论文列表：带上统计口径、当前年份与主选主题，保持与统计同一口径 */
const papersLink = computed(() => {
  const query: Record<string, string> = { from_stats: 'true' }
  const series = primaryKey.value
  if (series) {
    query.topic = series.key
    query.topic_name = series.name
  }
  if (conferences.value.length) query.conf = conferences.value.join(',')
  if (currentYear.value !== null) {
    query.year_from = String(currentYear.value)
    query.year_to = String(currentYear.value)
  }
  return { path: '/papers', query }
})

function currentScope() {
  return {
    conferences: [...conferences.value],
    yearFrom: yearFrom.value,
    yearTo: yearTo.value,
  }
}

async function loadScope(): Promise<void> {
  const token = ++trendToken
  loading.value = true
  loadError.value = ''
  try {
    const [summaryData, options] = await Promise.all([
      fetchSummary(currentScope()),
      fetchTop(currentScope(), { limit: 50 }),
    ])
    if (token !== trendToken) return
    summary.value = summaryData
    keyOptions.value = options.items
    const years = summaryData.years ?? []
    if (yearFrom.value === null && yearTo.value === null && years.length) {
      yearFrom.value = years[0] ?? null
      yearTo.value = years[years.length - 1] ?? null
    }
    if (currentYear.value === null && years.length) currentYear.value = years[0] ?? null
    // 未指定研究对象时默认比较范围内最热的主题，避免进页面就是空白图
    if (!selectedKeys.value.length && options.items.length) {
      selectedKeys.value = [options.items[0]?.key ?? ''].filter(Boolean)
    }
  } catch (error) {
    if (token !== trendToken) return
    summary.value = null
    keyOptions.value = []
    if (error instanceof ApiError) {
      loadError.value = error.message
      loadErrorRetryable.value = error.isRetryable
    } else {
      console.error('加载趋势范围失败：', error)
      loadError.value = '加载趋势数据失败，请稍后重试。'
      loadErrorRetryable.value = true
    }
  } finally {
    if (token === trendToken) loading.value = false
  }
}

async function loadTrend(): Promise<void> {
  if (!selectedKeys.value.length) {
    trend.value = null
    return
  }
  const token = ++trendToken
  try {
    const data = await fetchTrend(currentScope(), { keys: selectedKeys.value })
    if (token !== trendToken) return
    trend.value = data
  } catch (error) {
    if (token !== trendToken) return
    trend.value = null
    if (error instanceof ApiError) loadError.value = error.message
    else console.error('加载趋势曲线失败：', error)
  }
}

/** 年度 Top 10：只在该视图下按年份请求；播放到结束年份后不再请求 */
async function loadYearRank(): Promise<void> {
  if (view.value !== 'rank' || currentYear.value === null) return
  const token = ++rankToken
  rankLoading.value = true
  try {
    const data = await fetchTop(
      { ...currentScope(), yearFrom: currentYear.value, yearTo: currentYear.value },
      { limit: 10 },
    )
    if (token !== rankToken) return
    yearRank.value = data
  } catch (error) {
    if (token !== rankToken) return
    yearRank.value = null
    console.error('加载年度榜单失败：', error)
  } finally {
    if (token === rankToken) rankLoading.value = false
  }
}

function setYear(year: number): void {
  currentYear.value = year
}

function stopPlay(): void {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
  playing.value = false
}

function play(): void {
  stopPlay()
  const start = yearFrom.value
  const end = yearTo.value
  if (start === null || end === null || activeYears.value.length === 0) return
  if (currentYear.value === null || currentYear.value >= end) setYear(start)
  playing.value = true
  timer = window.setInterval(() => {
    const current = currentYear.value
    if (current === null || end === null || current >= end) {
      // 播到结束年份自动停止，按钮文案变为「重播」
      stopPlay()
      return
    }
    setYear(current + 1)
  }, PLAY_INTERVAL_MS)
}

function togglePlay(): void {
  if (playing.value) {
    stopPlay()
    return
  }
  play()
}

function replay(): void {
  stopPlay()
  if (yearFrom.value !== null) setYear(yearFrom.value)
  play()
}

function switchView(next: 'trend' | 'rank'): void {
  view.value = next
}

function toggleKey(key: string): void {
  if (!key) return
  const current = selectedKeys.value
  if (current.includes(key)) {
    selectedKeys.value = current.filter((item) => item !== key)
    return
  }
  // 超过上限时挤掉最早选的一个，保证最近选择的一定在图上
  selectedKeys.value = [...current, key].slice(-MAX_KEYS)
}

function setPrimaryKey(key: string): void {
  const rest = selectedKeys.value.filter((item) => item !== key)
  selectedKeys.value = [key, ...rest].slice(0, MAX_KEYS)
}

function onSelectYear(year: number): void {
  stopPlay()
  setYear(year)
}

/** 下拉框选择：新选的放最前（作为对照的主对象），下拉框自身复位为空 */
function onPickKey(event: Event): void {
  const select = event.target as HTMLSelectElement
  setPrimaryKey(select.value)
  select.value = ''
}

async function retryLoad(): Promise<void> {
  await loadScope()
  await loadTrend()
}

function keyLabel(key: string): string {
  return (
    comparedKeys.value.find((series) => series.key === key)?.name ??
    keyOptions.value.find((item) => item.key === key)?.name ??
    key
  )
}

// 筛选变化：停止播放、把当前年份夹回区间内，并重建图表
watch([conferences, yearFrom, yearTo], () => {
  stopPlay()
  const years = activeYears.value
  if (currentYear.value === null || !years.includes(currentYear.value)) {
    currentYear.value = years[0] ?? null
  }
  void loadScope()
  void loadTrend()
})

watch(selectedKeys, () => {
  stopPlay()
  void loadTrend()
})

// 年份推进：年度榜单视图按年份逐年请求；趋势视图用已取回的数据本地切年
watch(currentYear, () => {
  if (view.value === 'rank') void loadYearRank()
})

watch(view, () => {
  if (view.value === 'rank') void loadYearRank()
})

// 离开页面必须释放计时器，避免残留（原型用 setInterval，组件化后必须清理）
onBeforeUnmount(stopPlay)

/** 支持从首页以 ?kw=<主题 slug 或名称> 与 ?conf= 带入条件 */
function applyRouteQuery(): void {
  const kw = route.query.kw
  if (typeof kw === 'string' && kw && !selectedKeys.value.includes(kw)) {
    selectedKeys.value = [kw]
  }
  const confRaw = typeof route.query.conf === 'string' ? route.query.conf : ''
  const parsed = confRaw
    .split(',')
    .filter((item): item is Conference => (allConferences as string[]).includes(item))
  if (parsed.length) conferences.value = parsed
}

onMounted(async () => {
  applyRouteQuery()
  await loadScope()
  await loadTrend()
})

watch(() => route.query.kw, applyRouteQuery)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="页面 2 / 热度走势对比"
      title="这个方向是在升温，还是已经降温？"
      description="按年份比较所选方向在各会议中的热度。纵轴可切换占比或论文数：占比用各会议自己的当年样本量作分母，跨会议比较时不会被会议规模差异带偏。"
    >
      <template #aside>
        <ul class="header-legend">
          <li v-for="item in trendLegend" :key="item.label">
            <span
              class="legend-mark"
              :class="`is-${item.shape}`"
              :style="{ background: item.color }"
              aria-hidden="true"
            ></span>
            {{ item.label }}
          </li>
        </ul>
      </template>
    </PageHeader>

    <section class="card filter-card">
      <div class="filter-row">
        <div class="topic-field">
          <label class="field-label" for="topic-select">
            研究对象（主题，最多 {{ MAX_KEYS }} 个）
          </label>
          <select
            id="topic-select"
            class="select topic-select"
            :value="''"
            @change="onPickKey($event)"
          >
            <option value="">— 从当前范围的主题里选择 —</option>
            <option v-for="item in keyOptions" :key="item.key" :value="item.key">
              {{ item.name }}（{{ item.count }} 篇）
            </option>
          </select>
          <div class="quick-row">
            <button
              v-for="item in keyOptions.slice(0, 4)"
              :key="item.key"
              type="button"
              class="quick-chip"
              :class="{ 'is-on': selectedKeys.includes(item.key) }"
              @click="setPrimaryKey(item.key)"
            >
              {{ item.name }}
            </button>
          </div>
          <p v-if="selectedKeys.length" class="topic-selected">
            正在比较：
            <button
              v-for="key in selectedKeys"
              :key="key"
              type="button"
              class="tag tag-button"
              :title="'点击移除'"
              @click="toggleKey(key)"
            >
              {{ keyLabel(key) }} ×
            </button>
          </p>
        </div>

        <ConferenceChips v-model="conferences" label="会议（可多选）" />

        <YearRangeSelect
          v-model:year-from="yearFrom"
          v-model:year-to="yearTo"
          :years="summary?.years ?? []"
          label="起止年份"
        />

        <div class="metric-field">
          <span class="field-label">纵轴</span>
          <div class="segmented" role="group" aria-label="纵轴指标">
            <button
              type="button"
              class="seg-btn"
              :class="{ 'is-on': valueMode === 'share' }"
              @click="valueMode = 'share'"
            >
              占比（%）
            </button>
            <button
              type="button"
              class="seg-btn"
              :class="{ 'is-on': valueMode === 'count' }"
              @click="valueMode = 'count'"
            >
              论文数（篇）
            </button>
          </div>
        </div>

        <div class="play-controls">
          <button type="button" class="btn btn-primary" @click="togglePlay">
            {{ playButtonText }}
          </button>
          <button type="button" class="btn btn-secondary" :disabled="!playing" @click="stopPlay">
            暂停
          </button>
          <button type="button" class="btn btn-secondary" @click="replay">重播</button>
        </div>
      </div>

      <div class="progress-row">
        <ol class="year-cells">
          <li v-for="year in activeYears" :key="year">
            <button
              type="button"
              class="year-cell"
              :class="{
                'is-current': year === currentYear,
                'is-done': currentYear !== null && year < currentYear,
              }"
              @click="onSelectYear(year)"
            >
              <span>{{ year }} 年</span>
              <span class="year-bar" aria-hidden="true"></span>
            </button>
          </li>
        </ol>
        <div class="current-year">
          当前年份：<strong>{{ currentYearText }}</strong>
          <span class="current-hint">（点年份格或曲线上的数据点可直接定位）</span>
        </div>
      </div>
    </section>

    <p v-if="loadError" class="card load-error" role="alert">
      <span>{{ loadError }}</span>
      <button v-if="loadErrorRetryable" type="button" class="btn btn-secondary" @click="retryLoad">
        重试
      </button>
    </p>

    <div class="view-tabs">
      <button
        type="button"
        class="tab-btn"
        :class="{ 'is-on': view === 'trend' }"
        @click="switchView('trend')"
      >
        热度趋势曲线
      </button>
      <button
        type="button"
        class="tab-btn"
        :class="{ 'is-on': view === 'rank' }"
        @click="switchView('rank')"
      >
        年度 Top 10 演变
      </button>
    </div>

    <section v-if="view === 'trend'" class="trend-grid">
      <ChartContainer
        :title="`热度走势 · ${comparedKeys.map((series) => series.name).join(' / ') || '未选择主题'}`"
        subtitle="纵轴 = 该会议当年包含该主题的论文数 ÷ 该会议当年纳入分析的论文总数；缺失年份断开曲线，零值落在 0 轴"
        :unit="`单位：${unit}`"
        height="430px"
        :legend="[]"
        :status-text="`当前播放年份：${currentYearText}`"
      >
        <TrendChart
          v-if="trendLines.length"
          :years="trend?.years ?? []"
          :lines="trendLines"
          :unit="unit"
          :current-year="currentYear"
          height="430px"
          @select-year="onSelectYear"
        />
        <div v-else class="chart-placeholder">
          <p class="chart-placeholder-title">
            {{ loading ? '正在加载趋势数据…' : '请选择至少一个研究对象' }}
          </p>
          <p class="chart-placeholder-note">
            {{
              loading
                ? '正在请求 /api/stats/trend'
                : '从上方下拉框或快捷按钮选择主题后，这里会显示它在各会议中的逐年热度。'
            }}
          </p>
        </div>

        <template #footnote>
          <span>
            <strong>断点</strong>：该会议当年在库中没有记录（不等于热度为 0），图中画成灰色区间并断开曲线。
          </span>
          <span>
            <strong>0 轴上的点</strong>：该会议当年有样本，但没有匹配该主题的论文。
          </span>
          <span v-if="trend">
            当前范围共 {{ trend.key_total }} 个主题可用于比较；分母为各会议年份纳入分析的论文数，
            数据性质：{{ (trend.coverage.full_coverage_years ?? []).length }} 个会议年份为完整论文集{{ (trend.coverage.coverage_kinds?.sampled ?? 0) > 0 ? `，另有 ${trend.coverage.coverage_kinds.sampled} 个为抽样` : '' }}。
          </span>
          <span v-if="comparedKeys.length > 1">
            比较多个主题时<strong>线型</strong>表示主题、<strong>颜色</strong>表示会议。
          </span>
          <span>
            本样本每个会议只有两个年份（CVPR 2024/2025、ICCV 2023/2025、ECCV 2022/2024），
            因此同一会议的相邻年份线段只在 CVPR 2024→2025 处出现；其余年份按缺失处理并断开，
            这不是「热度为 0」。
          </span>
        </template>
      </ChartContainer>

      <div class="trend-side">
        <section class="card side-card">
          <h3 class="side-title">当前状态</h3>
          <dl class="side-list">
            <div>
              <dt>播放年份</dt>
              <dd class="side-strong">{{ currentYearText }} 年</dd>
            </div>
            <div>
              <dt>已选会议</dt>
              <dd>{{ conferences.length ? conferences.join(' · ') : '未选择' }}</dd>
            </div>
            <div>
              <dt>纵向指标</dt>
              <dd>{{ unit }}</dd>
            </div>
          </dl>

          <div class="side-section">
            <h4 class="side-subtitle">主题论文数与样本量</h4>
            <table class="side-table">
              <thead>
                <tr>
                  <th scope="col">会议</th>
                  <th v-for="series in comparedKeys" :key="series.key" scope="col">
                    {{ series.name }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in sideRows" :key="row.conference">
                  <th scope="row">
                    <span class="sample-conf">
                      <span
                        class="conf-dot"
                        :style="{ background: conferenceColors[row.conference] }"
                        aria-hidden="true"
                      ></span>
                      {{ row.conference }}
                    </span>
                  </th>
                  <td v-for="cell in row.cells" :key="`${row.conference}-${cell.key}`">
                    <span
                      v-if="!cell.point || cell.point.reason === 'no_records_in_sample'"
                      class="sample-none"
                    >
                      无记录
                    </span>
                    <span v-else class="sample-value">
                      {{ cell.point.count }} / {{ cell.point.denominator }} 篇 ·
                      <strong>{{ formatShare(cell.point.share) }}</strong>
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="card side-card">
          <h3 class="side-title">统计口径说明</h3>
          <ul class="side-notes">
            <li>· 占比 = 某会议某年份包含该主题的论文数 ÷ 该会议该年份纳入分析的论文总数 × 100%。</li>
            <li>· 分母只含「会议年份有效、标题可用、关键词已按当前规则版本处理完成」的论文。</li>
            <li>· 某会议年份在库中没有记录时<b>不画成 0</b>，而是断开曲线并标注灰色区间。</li>
            <li>· ICCV 为奇数年、ECCV 为偶数年，未采集的年份自然显示为无记录区间。</li>
          </ul>
          <p v-if="coverageHint" class="side-hint">{{ coverageHint }}</p>
          <p v-if="missingNow.length" class="side-hint">
            {{ missingNow.join('、') }} 在 {{ currentYearText }} 年没有可用数据，曲线在该年份断开。
          </p>
          <p v-if="zeroNow.length" class="side-hint">
            {{ zeroNow.join('、') }} 在 {{ currentYearText }} 年有样本但没有匹配该主题的论文，落在 0 轴。
          </p>
        </section>

        <RouterLink class="card side-link" :to="papersLink">
          想直接看这个方向的论文？
          <span>进入论文管理 →</span>
        </RouterLink>
      </div>
    </section>

    <section v-else class="card rank-card">
      <div class="card-header">
        <div>
          <h2 class="card-title">年度 Top 10 演变</h2>
          <p class="card-subtitle">
            {{ currentYearText }} 年各会议合并后的主题排名（先合并计数与分母再排序，同一篇论文只计一次）
          </p>
        </div>
        <div class="rank-year">
          当前年份：<strong>{{ currentYearText }}</strong>
          <span v-if="rankLoading" class="rank-loading">· 加载中…</span>
        </div>
      </div>
      <RankBarList
        v-if="rankItems.length"
        :items="rankItems"
        interactive
        @select="setPrimaryKey($event.key)"
      />
      <p v-else class="rank-placeholder">
        {{
          rankLoading
            ? '正在加载该年份榜单…'
            : `${currentYearText} 年没有可统计的主题（该年份可能没有采集记录）`
        }}
      </p>
      <div class="rank-footer">
        <span v-if="yearRank">
          分母 {{ yearRank.denominator }} 篇 · 该年记录 {{ yearRank.total_sample }} 篇 · 主题
          {{ yearRank.key_total }} 个
        </span>
        <RouterLink class="rank-link" :to="papersLink">查看该主题相关论文 →</RouterLink>
      </div>
    </section>

    <div class="topic-groups">
      <span class="group-note">
        会议配色在全站固定：CVPR 蓝、ICCV 青、ECCV 橙；曲线颜色只表示会议，
        比较多个主题时用线型区分主题，两者不混用同一个视觉通道。
      </span>
    </div>
  </div>
</template>

<style scoped>
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

.metric-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.segmented {
  display: inline-flex;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.seg-btn {
  padding: 6px 12px;
  border: 0;
  background: var(--color-surface);
  color: var(--color-text-muted);
  font-size: 13px;
  cursor: pointer;
}

.seg-btn + .seg-btn {
  border-left: 1px solid var(--color-border);
}

.seg-btn.is-on {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

.topic-selected {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.tag-button {
  border: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  cursor: pointer;
}

.tag-button:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.current-hint {
  margin-left: 8px;
  color: var(--color-text-faint);
  font-size: 11px;
}

.side-table {
  width: 100%;
  margin-top: 8px;
  border-collapse: collapse;
  font-size: 12px;
}

.side-table th,
.side-table td {
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid var(--color-border-soft);
  vertical-align: top;
}

.side-table thead th {
  color: var(--color-text-subtle);
  font-weight: 500;
}

.rank-loading {
  margin-left: 8px;
  color: var(--color-text-faint);
  font-size: 12px;
}

.rank-placeholder {
  padding: 24px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text-subtle);
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

.header-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.header-legend li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-mark {
  display: inline-block;
}

.legend-mark.is-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.legend-mark.is-line {
  width: 12px;
  height: 3px;
  border-radius: 2px;
}

.legend-mark.is-block {
  width: 16px;
  height: 12px;
  border-radius: 2px;
}

.filter-card {
  margin-bottom: 24px;
  padding: 20px 24px;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 20px 32px;
}

.topic-field {
  min-width: 260px;
}

.topic-select {
  width: 280px;
  max-width: 100%;
}

.quick-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.quick-chip {
  padding: 4px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-subtle);
  font-size: 11px;
  cursor: pointer;
}

.quick-chip:hover {
  background: var(--color-surface-muted);
}

.quick-chip.is-on {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

.play-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 20px;
}

.year-cells {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  flex: 1;
}

.year-cell {
  display: block;
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  color: var(--color-text-faint);
  font-size: 11px;
  text-align: left;
  cursor: pointer;
}

.year-cell.is-done {
  border-color: var(--color-border-strong);
  background: var(--color-surface);
  color: var(--color-text-subtle);
}

.year-cell.is-current {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

.year-bar {
  display: block;
  height: 6px;
  margin-top: 4px;
  border-radius: 999px;
  background: var(--color-inactive);
}

.year-cell.is-done .year-bar,
.year-cell.is-current .year-bar {
  background: var(--color-primary);
}

.current-year {
  width: 180px;
  flex: 0 0 auto;
  font-size: 14px;
  text-align: right;
  color: var(--color-text-muted);
}

.current-year strong {
  color: var(--color-primary);
  font-size: 16px;
}

.view-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.tab-btn {
  padding: 8px 16px;
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

.trend-grid {
  display: grid;
  grid-template-columns: minmax(0, 8fr) minmax(0, 4fr);
  gap: 24px;
  align-items: start;
}

.trend-side {
  display: grid;
  gap: 16px;
}

.side-card {
  padding: 20px 24px;
}

.side-title {
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.side-list {
  display: grid;
  gap: 10px;
}

.side-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 14px;
}

.side-list dt {
  color: var(--color-text-subtle);
}

.side-list dd {
  color: var(--color-text);
}

.side-list dd.side-strong {
  color: var(--color-primary);
  font-weight: 600;
}

.side-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-soft);
}

.side-subtitle {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.sample-list {
  display: grid;
  gap: 8px;
}

.sample-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  font-size: 12px;
}

.sample-conf {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-muted);
}

.sample-none {
  color: var(--color-text-faint);
}

.sample-value {
  color: var(--color-text-subtle);
}

.sample-value strong {
  color: var(--color-text-strong);
}

.side-notes {
  display: grid;
  gap: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-subtle);
}

.side-hint {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.side-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 24px;
  font-size: 14px;
  color: var(--color-text-muted);
}

.side-link:hover {
  border-color: var(--color-primary);
}

.side-link span {
  color: var(--color-primary);
  font-weight: 500;
}

.rank-card {
  margin-bottom: 24px;
}

.rank-year {
  font-size: 14px;
  color: var(--color-text-muted);
}

.rank-year strong {
  color: var(--color-primary);
}

.topic-groups {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.topic-groups .tag {
  gap: 6px;
}

.group-note {
  font-size: 11px;
  color: var(--color-text-faint);
}

/* 窄窗口：主区与侧栏改为单列，播放控件换行 */
@media (max-width: 1200px) {
  .trend-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .progress-row {
    flex-direction: column;
    align-items: stretch;
  }

  .current-year {
    width: auto;
    text-align: left;
  }

  .play-controls {
    margin-left: 0;
  }
}

@media (max-width: 700px) {
  .year-cells {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .topic-select {
    width: 100%;
  }
}
</style>
