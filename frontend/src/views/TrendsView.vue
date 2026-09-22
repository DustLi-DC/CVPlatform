<script setup lang="ts">
/**
 * 页面 2 · 热度走势对比（对应原型 02_trends）。
 *
 * 本阶段实现：主题/会议/年份筛选、播放·暂停·重播控制、年份进度定位、两个视图切换、
 * 样本量侧栏与统计口径说明。播放推进的是**界面状态**（每 900ms 前进一步，与原型一致），
 * 曲线本身由 ECharts 渲染，在阶段 9 接入真实趋势数据后实现。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import ChartContainer from '../components/ChartContainer.vue'
import ConferenceChips from '../components/ConferenceChips.vue'
import PageHeader from '../components/PageHeader.vue'
import RankBarList, { type RankItem } from '../components/RankBarList.vue'
import YearRangeSelect from '../components/YearRangeSelect.vue'
import { demoYearFirst, demoYearLast, demoYears } from '../demo/coverage'
import {
  defaultTrendTopic,
  demoConferenceYearSample,
  demoTopicCount,
  demoTrendTopics,
  findDemoTopic,
  topicGroupColors,
  topicGroupLabels,
} from '../demo/topics'
import { conferenceColors, type Conference } from '../types/paper'

const route = useRoute()

const PLAY_INTERVAL_MS = 900

const topicName = ref(defaultTrendTopic)
const conferences = ref<Conference[]>(['CVPR', 'ICCV', 'ECCV'])
const yearFrom = ref<number>(demoYearFirst)
const yearTo = ref<number>(demoYearLast)
const currentYear = ref<number>(demoYearFirst)
const view = ref<'trend' | 'rank'>('trend')
const playing = ref(false)

let timer: number | null = null

const activeYears = computed(() =>
  demoYears.filter((year) => year >= yearFrom.value && year <= yearTo.value),
)

const currentTopic = computed(() => findDemoTopic(topicName.value))

interface ConferenceSample {
  conference: Conference
  count: number | null
  sample: number | null
  share: number | null
}

const sampleList = computed<ConferenceSample[]>(() => {
  const topic = currentTopic.value
  return conferences.value.map((conference) => {
    const sample = demoConferenceYearSample(conference, currentYear.value)
    const count = topic ? demoTopicCount(topic, conference, currentYear.value) : null
    return {
      conference,
      count,
      sample,
      share: sample && count !== null ? (count / sample) * 100 : null,
    }
  })
})

const rankItems = computed<RankItem[]>(() =>
  demoTrendTopics
    .map((topic) => ({
      name: topic.name,
      group: topic.group,
      count: conferences.value.reduce(
        (sum, conference) => sum + (demoTopicCount(topic, conference, currentYear.value) ?? 0),
        0,
      ),
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10)
    .map((row) => ({
      key: row.name,
      label: row.name,
      count: row.count,
      color: topicGroupColors[row.group],
      active: row.name === topicName.value,
    })),
)

const trendLegend = computed(() => [
  ...conferences.value.map((conference) => ({
    label: conference,
    color: conferenceColors[conference],
    shape: 'line' as const,
  })),
  { label: '无数据区间', color: 'var(--color-inactive)', shape: 'block' as const },
])

const coverageHint = computed(() => {
  const missing = sampleList.value.filter((item) => item.sample === null)
  if (!missing.length) return ''
  return `${missing.map((item) => item.conference).join('、')} 在 ${currentYear.value} 年没有可用数据，趋势图中显示为灰色区间并断开曲线，不按 0 热度处理。`
})

/** 表格中的一个零值点：有样本但该主题当年未被检索到，落在 0 轴 */
const zeroPointHint = computed(() => {
  const zero = sampleList.value.find((item) => item.sample !== null && item.count === 0)
  if (!zero) return ''
  return `${zero.conference} ${currentYear.value} 年有样本但没有匹配该主题的论文，图中落在 0 轴。`
})

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
  if (currentYear.value >= yearTo.value) setYear(yearFrom.value)
  playing.value = true
  timer = window.setInterval(() => {
    if (currentYear.value >= yearTo.value) {
      stopPlay()
      return
    }
    setYear(currentYear.value + 1)
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
  setYear(yearFrom.value)
  play()
}

function switchView(next: 'trend' | 'rank'): void {
  view.value = next
}

// 筛选改变时重置播放范围，避免停在区间外（与原型一致）
watch([yearFrom, yearTo], () => {
  if (currentYear.value < yearFrom.value || currentYear.value > yearTo.value) {
    setYear(yearFrom.value)
  }
  stopPlay()
})

watch(topicName, () => stopPlay())

// 离开页面必须释放计时器，避免残留
onBeforeUnmount(stopPlay)

// 支持从首页以 ?kw= 带入主题
watch(
  () => route.query.kw,
  (value) => {
    if (typeof value === 'string' && findDemoTopic(value)) topicName.value = value
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="页面 2 / 热度走势对比"
      title="这个方向是在升温，还是已经降温？"
      description="选择研究方向与会议，逐年比较它在 CVPR、ICCV、ECCV 中的占比变化。曲线上的断点表示该会议当年没有可用数据，与「有数据但该主题出现 0 次」在图中是两种不同的画法。"
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
          <label class="field-label" for="topic-select">研究方向 / 关键词</label>
          <select id="topic-select" v-model="topicName" class="select topic-select">
            <option v-for="topic in demoTrendTopics" :key="topic.name" :value="topic.name">
              {{ topic.name }}
            </option>
          </select>
          <div class="quick-row">
            <button
              v-for="topic in demoTrendTopics.slice(0, 3)"
              :key="topic.name"
              type="button"
              class="quick-chip"
              :class="{ 'is-on': topic.name === topicName }"
              @click="topicName = topic.name"
            >
              {{ topic.name }}
            </button>
          </div>
        </div>

        <ConferenceChips v-model="conferences" label="会议（可多选）" />

        <YearRangeSelect v-model:year-from="yearFrom" v-model:year-to="yearTo" :years="demoYears" label="起止年份" />

        <div class="play-controls">
          <button type="button" class="btn btn-primary" @click="togglePlay">
            {{ playing ? '播放中' : currentYear >= yearTo ? '重播' : '播放' }}
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
              :class="{ 'is-current': year === currentYear, 'is-done': year < currentYear }"
              @click="
                () => {
                  stopPlay()
                  setYear(year)
                }
              "
            >
              <span>{{ year }} 年</span>
              <span class="year-bar" aria-hidden="true"></span>
            </button>
          </li>
        </ol>
        <div class="current-year">
          当前年份：<strong>{{ currentYear }}</strong>
        </div>
      </div>
    </section>

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
        :title="`热度走势 · ${topicName}`"
        subtitle="纵轴热度 = 该会议当年包含该主题的论文数 ÷ 当年纳入分析的论文总数 × 100%"
        unit="单位：%"
        height="400px"
        :legend="[]"
        :status-text="`当前播放年份：${currentYear}（演示）`"
        pending-note="趋势曲线由 ECharts 渲染，将在阶段 9 接入真实趋势数据后实现：缺失年份显示为灰色区间且曲线断开，有样本但主题为 0 的点落在 0 轴。"
      />

      <div class="trend-side">
        <section class="card side-card">
          <h3 class="side-title">当前状态</h3>
          <dl class="side-list">
            <div>
              <dt>已选主题</dt>
              <dd>{{ topicName }}</dd>
            </div>
            <div>
              <dt>播放年份</dt>
              <dd class="side-strong">{{ currentYear }} 年</dd>
            </div>
            <div>
              <dt>已选会议</dt>
              <dd>{{ conferences.length ? conferences.join(' · ') : '未选择' }}</dd>
            </div>
          </dl>

          <div class="side-section">
            <h4 class="side-subtitle">主题论文数与样本量</h4>
            <div class="sample-list">
              <div v-for="item in sampleList" :key="item.conference" class="sample-item">
                <span class="sample-conf">
                  <span
                    class="conf-dot"
                    :style="{ background: conferenceColors[item.conference] }"
                    aria-hidden="true"
                  ></span>
                  {{ item.conference }}
                </span>
                <span v-if="item.sample === null" class="sample-none">
                  {{ currentYear }} 年无可用数据
                </span>
                <span v-else class="sample-value">
                  {{ item.count }} / {{ item.sample.toLocaleString('zh-CN') }} 篇 ·
                  <strong>{{ item.share === null ? '—' : item.share.toFixed(2) }}%</strong>
                </span>
              </div>
            </div>
          </div>
        </section>

        <section class="card side-card">
          <h3 class="side-title">统计口径说明</h3>
          <ul class="side-notes">
            <li>· 热度 = 某会议某年份包含该主题的论文数 ÷ 该会议该年份纳入分析的论文总数 × 100%。</li>
            <li>· ICCV 为奇数年会议、ECCV 为偶数年会议，其余年份显示为「无数据」灰色区间，不按 0 热度处理。</li>
            <li>· 曲线落在 0 轴上的点表示<strong>有数据、但该主题未被检索到</strong>。</li>
            <li>· 当前为演示数据，结论仅用于课程展示。</li>
          </ul>
          <p v-if="coverageHint" class="side-hint">{{ coverageHint }}</p>
          <p v-if="zeroPointHint" class="side-hint">{{ zeroPointHint }}</p>
        </section>

        <RouterLink class="card side-link" :to="{ path: '/papers', query: { kw: topicName } }">
          想直接看这个方向的论文？
          <span>进入论文管理 →</span>
        </RouterLink>
      </div>
    </section>

    <section v-else class="card rank-card">
      <div class="card-header">
        <div>
          <h2 class="card-title">年度 Top 10 演变</h2>
          <p class="card-subtitle">按播放年份逐帧展示排名变化，观察热词如何上下浮动（演示数据）</p>
        </div>
        <div class="rank-year">当前年份：<strong>{{ currentYear }}</strong></div>
      </div>
      <RankBarList
        :items="rankItems"
        :interactive="true"
        @select="
          (item) => {
            topicName = item.key
          }
        "
      />
    </section>

    <div class="topic-groups">
      <span v-for="(label, group) in topicGroupLabels" :key="group" class="tag">
        <span
          class="legend-mark is-dot"
          :style="{ background: topicGroupColors[group] }"
          aria-hidden="true"
        ></span>
        {{ label }}
      </span>
      <span class="group-note">主题分组色仅用于辅助辨识，与会议色是两套独立概念。</span>
    </div>
  </div>
</template>

<style scoped>
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
