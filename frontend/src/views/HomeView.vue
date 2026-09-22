<script setup lang="ts">
/**
 * 页面 1 · 热门方向总览（对应原型 01_home）。
 *
 * 本阶段所有数值来自 src/demo 下的演示数据，页面已标注演示来源；统计接口在阶段 8
 * 接入后替换数据来源，页面结构与交互保持不变。
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import ChartContainer from '../components/ChartContainer.vue'
import ConferenceChips from '../components/ConferenceChips.vue'
import DemoNotice from '../components/DemoNotice.vue'
import PageHeader from '../components/PageHeader.vue'
import PaperDrawer from '../components/PaperDrawer.vue'
import RankBarList, { type RankItem } from '../components/RankBarList.vue'
import StatCard from '../components/StatCard.vue'
import YearRangeSelect from '../components/YearRangeSelect.vue'
import { DEMO_SUFFIX, demoCoverage, demoYearFirst, demoYearLast, demoYears } from '../demo/coverage'
import { demoDrawerPapers } from '../demo/papers'
import {
  demoConferenceYearSample,
  demoGraphEdges,
  demoTopicCount,
  demoTrendTopics,
  findDemoTopic,
  topicGroupColors,
  topicGroupLabels,
} from '../demo/topics'
import { conferenceColors, type Conference } from '../types/paper'

const route = useRoute()
const router = useRouter()

const conferences = ref<Conference[]>(['CVPR', 'ICCV', 'ECCV'])
const yearFrom = ref<number>(demoYearFirst)
const yearTo = ref<number>(demoYearLast)
const activeTopic = ref('')

const activeYears = computed(() =>
  demoYears.filter((year) => year >= yearFrom.value && year <= yearTo.value),
)

const yearRangeLabel = computed(() => `${yearFrom.value}—${yearTo.value}`)

const sampleTotal = computed(() =>
  conferences.value.reduce(
    (sum, conference) =>
      sum +
      activeYears.value.reduce(
        (inner, year) => inner + (demoConferenceYearSample(conference, year) ?? 0),
        0,
      ),
    0,
  ),
)

interface TopicRow {
  name: string
  group: keyof typeof topicGroupColors
  count: number
}

const topicRows = computed<TopicRow[]>(() =>
  demoTrendTopics
    .map((topic) => ({
      name: topic.name,
      group: topic.group,
      count: conferences.value.reduce(
        (sum, conference) =>
          sum +
          activeYears.value.reduce(
            (inner, year) => inner + (demoTopicCount(topic, conference, year) ?? 0),
            0,
          ),
        0,
      ),
    }))
    .sort((a, b) => b.count - a.count),
)

const rankItems = computed<RankItem[]>(() =>
  topicRows.value
    .filter((row) => row.count > 0)
    .slice(0, 10)
    .map((row) => ({
      key: row.name,
      label: row.name,
      count: row.count,
      color: topicGroupColors[row.group],
      active: row.name === activeTopic.value,
    })),
)

/**
 * 范围最热方向。计数为 0 时视为「没有可用样本」而非「最热方向是 0 篇」——
 * 与统计口径一致：分母为 0 或数据缺失时应显示缺失状态，不写成 0。
 */
const hottestTopic = computed(() => {
  const first = topicRows.value[0]
  return first && first.count > 0 ? first : null
})

/** 所选会议在年份区间内完全没有数据的提示（对应原型的灰色缺口说明） */
const missingConferences = computed(() =>
  conferences.value.filter(
    (conference) =>
      !activeYears.value.some(
        (year) => typeof demoConferenceYearSample(conference, year) === 'number',
      ),
  ),
)

const scopeText = computed(() => {
  const conferenceLabel = conferences.value.length ? conferences.value.join(' · ') : '未选择会议'
  return { conferenceLabel, rangeLabel: yearRangeLabel.value }
})

const graphLegend = computed(() =>
  (Object.keys(topicGroupLabels) as (keyof typeof topicGroupLabels)[]).map((group) => ({
    label: topicGroupLabels[group],
    color: topicGroupColors[group],
    shape: 'dot' as const,
  })),
)

const activeTopicCount = computed(() => {
  const topic = findDemoTopic(activeTopic.value)
  if (!topic) return 0
  return conferences.value.reduce(
    (sum, conference) =>
      sum +
      activeYears.value.reduce(
        (inner, year) => inner + (demoTopicCount(topic, conference, year) ?? 0),
        0,
      ),
    0,
  )
})

const activeTopicShare = computed(() => {
  if (sampleTotal.value === 0) return null
  return (activeTopicCount.value / sampleTotal.value) * 100
})

const drawerCoTopics = computed(() => {
  if (!activeTopic.value) return []
  return demoGraphEdges
    .filter((edge) => edge.source === activeTopic.value || edge.target === activeTopic.value)
    .map((edge) => ({
      name: edge.source === activeTopic.value ? edge.target : edge.source,
      weight: edge.weight,
    }))
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 4)
})

const drawerPapers = computed(() => {
  if (!activeTopic.value) return []
  // 演示数据里按主题归属挑示例论文；阶段 8 起改用统计接口返回的真实关联论文
  return demoDrawerPapers.filter((paper) => paper.topics.includes(activeTopic.value)).slice(0, 3)
})

const drawerQuery = computed(() => ({
  kw: activeTopic.value,
  conf: conferences.value.join(','),
  year_from: String(yearFrom.value),
  year_to: String(yearTo.value),
}))

const trendEntryTopics = computed(() =>
  demoTrendTopics.slice(0, 3).map((topic, index) => ({
    name: topic.name,
    conference: (['CVPR', 'ICCV', 'ECCV'] as Conference[])[index] ?? 'CVPR',
    hint:
      ['2022—2025 全部年份可用', '注：ICCV 仅奇数年有数据', '2023 年起才零散出现'][index] ?? '',
  })),
)

function resetFilters(): void {
  conferences.value = ['CVPR', 'ICCV', 'ECCV']
  yearFrom.value = demoYearFirst
  yearTo.value = demoYearLast
}

function openTopicDrawer(name: string): void {
  activeTopic.value = name
  void router.replace({ query: { ...route.query, kw: name } })
}

function closeDrawer(): void {
  activeTopic.value = ''
  const query = { ...route.query }
  delete query.kw
  void router.replace({ query })
}

// 支持从趋势页或列表页以 ?kw= 直接带入主题，与原型一致
watch(
  () => route.query.kw,
  (value) => {
    if (typeof value === 'string' && findDemoTopic(value)) activeTopic.value = value
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <PageHeader
      variant="hero"
      eyebrow="页面 1 / 热门方向总览"
      title="计算机视觉顶会热词分析"
      description="面向刚接触计算机视觉的同学：把 CVPR、ICCV、ECCV 近几年的论文题目与摘要放在一起统计，先看清哪些方向在被反复研究，再顺着热词找到值得读的论文。"
      notice="本页榜单、图谱与所有数值均为课程演示数据，不代表已核验的研究结论。"
      :stats="[
        { label: '纳入论文样本', value: sampleTotal.toLocaleString('zh-CN'), hint: '篇（演示）' },
        { label: '覆盖会议年份', value: String(demoCoverage.length), hint: '个组合' },
      ]"
    />

    <section class="card filter-card">
      <div class="filter-row">
        <ConferenceChips v-model="conferences" />
        <YearRangeSelect v-model:year-from="yearFrom" v-model:year-to="yearTo" :years="demoYears" />
        <div class="filter-scope">
          <span class="field-label">当前统计范围</span>
          <p class="scope-text">
            <strong>{{ scopeText.conferenceLabel }}</strong>
            ｜ {{ scopeText.rangeLabel }} 年 ｜ 纳入论文样本
            <strong class="scope-strong">{{ sampleTotal.toLocaleString('zh-CN') }}</strong>
            篇（演示数据）
          </p>
        </div>
        <button type="button" class="btn btn-secondary" @click="resetFilters">重置筛选</button>
      </div>

      <DemoNotice v-if="missingConferences.length" class="filter-notice" tone="warn">
        {{ missingConferences.join('、') }} 在所选年份区间内没有可用数据（例如 ICCV 为奇数年会议、
        ECCV 为偶数年会议），这部分年份不会被当作零热度统计。
      </DemoNotice>
    </section>

    <section class="kpi-grid">
      <StatCard
        label="统计范围内论文样本"
        :value="sampleTotal.toLocaleString('zh-CN')"
        :hint="`按会议年份纳入分析的总篇数${DEMO_SUFFIX}`"
      />
      <StatCard label="出现过的关键词" value="386" :hint="`系统提取后去重${DEMO_SUFFIX}`" />
      <StatCard
        label="范围最热方向"
        :value="hottestTopic ? hottestTopic.name : '—'"
        :hint="hottestTopic ? `${hottestTopic.count} 篇相关论文` : '当前范围没有可用样本'"
      />
      <StatCard
        label="数据更新时间"
        value="09-20"
        :hint="`2026-09-20 22:10 同步${DEMO_SUFFIX}`"
      />
    </section>

    <section class="main-grid">
      <div class="card rank-card">
        <div class="card-header">
          <div>
            <h2 class="card-title">Top 10 热门研究方向</h2>
            <p class="card-subtitle">按当前统计范围内包含该方向的论文数排序（演示数据）</p>
          </div>
          <span class="tag">单位：篇</span>
        </div>
        <RankBarList :items="rankItems" @select="openTopicDrawer($event.key)" />
        <div class="rank-footer">
          <span>点击任意方向可查看相关论文</span>
          <RouterLink class="rank-link" to="/papers">进入论文管理 →</RouterLink>
        </div>
      </div>

      <ChartContainer
        title="关键词关系图谱"
        subtitle="共现关系取自论文题目与摘要的共词统计（演示数据）"
        :legend="graphLegend"
        height="430px"
        pending-note="图谱由 ECharts 渲染，将在阶段 8 接入真实统计接口后实现（节点大小 ∝ √相关论文数，连线粗细 ∝ 共现论文数）。"
      >
        <template #footnote>
          <span>
            <strong>节点</strong>：一个主题；<strong>节点越大</strong>，表示当前范围内与它相关的论文越多。
          </span>
          <span>
            <strong>连线</strong>：两个主题在同一篇论文中出现过；<strong>越粗</strong>表示共现论文数越多。
          </span>
          <span>当前筛选下榜单条目数：{{ rankItems.length }}（演示）</span>
        </template>
      </ChartContainer>
    </section>

    <section class="card trend-entry">
      <div class="trend-entry-main">
        <h2 class="card-title">下一步：把「现在很热」变成「怎么变热的」</h2>
        <p class="trend-entry-desc">
          进入热度走势对比，选择研究方向与会议，逐年播放 2022—2025 的热度曲线，看清某个方向是在持续升温，
          还是已经开始降温。
        </p>
        <div class="trend-entry-actions">
          <RouterLink
            class="btn btn-primary"
            :to="{
              path: '/trends',
              query: {
                kw: hottestTopic ? hottestTopic.name : undefined,
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
          v-for="item in trendEntryTopics"
          :key="item.name"
          class="trend-entry-card"
          :to="{ path: '/trends', query: { kw: item.name } }"
        >
          <span class="trend-entry-conf">
            <span
              class="conf-dot"
              :style="{ background: conferenceColors[item.conference] }"
              aria-hidden="true"
            ></span>
            {{ item.conference }}
          </span>
          <span class="trend-entry-topic">{{ item.name }}</span>
          <span class="trend-entry-hint">{{ item.hint }}</span>
        </RouterLink>
      </div>
    </section>

    <PaperDrawer
      :open="Boolean(activeTopic)"
      :topic-name="activeTopic"
      :count="activeTopicCount"
      :share="activeTopicShare"
      :co-topics="drawerCoTopics"
      :papers="drawerPapers"
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

.filter-notice {
  margin-top: 16px;
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
