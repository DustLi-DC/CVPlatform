<script setup lang="ts">
/**
 * 热度走势曲线（ECharts line），按原型规范渲染：
 *
 * - 横轴为年份，纵轴按「占比（%）」或「论文数（篇）」切换，单位在图例与轴名上标明；
 * - 一条曲线 = 一个会议（配色沿用全站会议色）；比较多个主题时用线型区分主题，
 *   颜色始终表示会议，避免两套含义混在同一个视觉通道里；
 * - 缺失分三种，画法不同：
 *   1) **该届不举办**（ICCV 偶数年、ECCV 奇数年）：浅色区间 + 「该届不举办」，曲线跨过；
 *   2) **该届存在但按完整度策略跳过**（如 ECCV 2026 摘要不完整）：不画任何区间标注，
 *      只是没有数据点——它是本次范围之外，不是缺口；
 *   3) **范围内该届没有采到数据**：灰色区间 + 「无数据」，曲线在此断开；
 * - 有样本但计数为 0 的点落在 0 轴上——与上面两种情况都不同（null 与 0 在 ECharts 里画法不同）。
 *
 * 动画（本轮改造）：
 * - **年份推进不再整图重绘**。此前每次改年份都 `setOption(option, true)`，ECharts 的过渡动画
 *   会被 notMerge 整体重置，视觉上是"跳一格"而不是"走过去"。现在把 option 拆成两层：
 *   数据层（年份轴、系列、区间）只在数据变化时重建，年份层用合并更新，保留 ECharts 的过渡；
 * - **播放头画成 DOM 覆盖层，而不是画在 canvas 上**：虚线、年份标签、光带是一个绝对定位的元素，
 *   靠 CSS `transform` 过渡滑行（700ms，略短于 900ms 的播放步长，每次推进都能落定再走下一格）。
 *   画在 canvas 上的话每帧都要重绘，且 markLine 的移动不会补间；
 * - 播放头横坐标由「网格内边距 + 容器宽度 + 年份序号」直接算出，与 option.grid 共用同一组常量，
 *   避免两处各写一份而漂移（`boundaryGap: false` 时首尾年份正好落在绘图区左右边缘）；
 * - 当前年份的数据点放大一档，让游标经过的地方在曲线上也能看出来；
 * - **播放时曲线与数据点随年份逐步绘制**：播放中把截止点之后的年份置为 null（`connectNulls`
 *   的语义不受影响——被置空的只是尚未"发生"的年份，范围内的跨年连线与断点照旧），
 *   每推进一格就多画出一段线和一个点；播放头正好压在正在生长的那个点上。
 *   区间标注（无数据/该届不举办）同样只标到截止点，避免还没播放到的年份提前出现灰块。
 *   暂停或播放结束后恢复完整曲线——页面的本职仍是"看整段走势"，逐步绘制只是播放时的效果；
 * - 提示框区分两种"空"：播放中尚未绘制 → 「尚未绘制」，库里真的没有数据 → 「无数据」；
 * - `prefers-reduced-motion: reduce` 时关闭过渡与入场动画（播放头直接跳到位）；
 * - ECharts 挂在一个**专属宿主 div** 上：它会在自己的容器里插 DOM，若与播放头共用同一个
 *   Vue 管理的父节点，两边的插入会互相覆盖——实测表现为 VNode 里有播放头而真实 DOM 里
 *   被替换成空 div（Vue 的 patch 与 ECharts 的插入不同步）。
 *
 * 生命周期：容器尺寸变化跟随（ResizeObserver + window.resize，回调走定时器，
 * 页面渲染暂停时 rAF 不会触发），组件卸载时移除监听并 dispose 实例。
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import { echarts, resolveCssColor } from '../composables/echarts'
// 布局常量与 GIF 导出共用一份（见 composables/trendLayout.ts）：
// 组件、播放头覆盖层、导出时的手绘播放头三处必须用同一组数字
import {
  PLAYHEAD_SLIDE_MS,
  SYMBOL_SIZE,
  SYMBOL_SIZE_ACTIVE,
  TREND_GRID as GRID,
} from '../composables/trendLayout'
import type { ComposeOption } from 'echarts/core'
import type { LineSeriesOption } from 'echarts/charts'
import type {
  GridComponentOption,
  LegendComponentOption,
  MarkAreaComponentOption,
  TooltipComponentOption,
} from 'echarts/components'

export interface TrendLine {
  /** 系列唯一键 */
  key: string
  /** 图例名（会议名，或多个主题时的「主题 · 会议」） */
  label: string
  /** 线条颜色：可直接传设计令牌（如 var(--color-conf-cvpr)），组件画到 canvas 前会解析 */
  color: string
  /** 比较多个主题时用线型区分主题 */
  lineType: 'solid' | 'dashed' | 'dotted'
  /** 与 years 等长的取值，null 表示该年份没有记录 */
  values: (number | null)[]
  /** 该线在这些年份没有采到数据（真缺口）：画灰色区间，曲线断开 */
  missingYears?: number[]
  /** 该线在这些年份该届不举办（如 ICCV 偶数年）：画浅色区间，曲线跨过该年份连线 */
  absentYears?: number[]
}

const props = withDefaults(
  defineProps<{
    years: number[]
    lines: TrendLine[]
    /** 纵轴单位，如「占比（%）」 */
    unit: string
    /** 当前年份：播放头停在这一年 */
    currentYear: number | null
    height?: string
    /** 数值提示里的额外说明，如「分母」来源 */
    valueLabel?: string
    /** 播放中：播放头带呼吸效果，暂停时静止 */
    playing?: boolean
  }>(),
  { height: '400px', valueLabel: '值', currentYear: null, playing: false },
)

const emit = defineEmits<{
  selectYear: [year: number]
}>()

/** 交给样式里的 v-bind 用（CSS 里写模板字符串容易被引号绊住） */
const playheadSlide = `${PLAYHEAD_SLIDE_MS}ms`

const container = ref<HTMLDivElement | null>(null)
/** ECharts 的专属宿主：图表只在这一个节点里插 DOM，不再与播放头争同一个父节点 */
const chartHost = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
/** 绘图区宽度：播放头按它算横坐标，尺寸变化时更新 */
const plotWidth = ref(0)
const reducedMotion = ref(false)
let resizeObserver: ResizeObserver | null = null

type ChartOption = ComposeOption<
  | LineSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | MarkAreaComponentOption
  | TooltipComponentOption
>

/** markArea 的两维元组类型：需要恰好两个端点，写成元组才能满足 ECharts 的类型 */
type MarkAreaLabel = { show: boolean; color?: string; fontSize?: number; formatter?: string }

type MarkAreaPair = [
  { xAxis: string; itemStyle?: { color: string }; label?: MarkAreaLabel },
  { xAxis: string },
]

const yearIndex = computed(() => {
  const year = props.currentYear
  if (year === null) return -1
  return props.years.indexOf(year)
})

/**
 * 绘制截止点（年份序号）：播放中等于当前年份，其余时候为 null（画完整曲线）。
 * 只依赖 playing + currentYear，因此播放推进时每格都会重算 → 曲线逐年生长。
 */
const revealCutoff = computed<number | null>(() => {
  if (!props.playing) return null
  const index = yearIndex.value
  return index < 0 ? null : index
})

/**
 * 逐点数据：
 * - 播放中把截止点之后的年份置为 null，曲线到此为止（`connectNulls` 只影响范围内，
 *   因此不举办年份的跨连、真缺口的断开都不受影响）；
 * - 当前年份的点放大一档，让"正在被画出来"的那个点看得见。
 */
function pointData(line: TrendLine): { value: number | null; symbolSize: number }[] {
  const activeIndex = yearIndex.value
  const cutoff = revealCutoff.value
  return line.values.map((value, index) => ({
    value: cutoff !== null && index > cutoff ? null : value,
    symbolSize: index === activeIndex ? SYMBOL_SIZE_ACTIVE : SYMBOL_SIZE,
  }))
}

/**
 * 缺失/不举办区间：播放中同样只标到截止点，否则还没播放到的年份会先亮起灰块。
 * 始终返回对象（数据可能为空）——合并更新时用空数组才能可靠清掉上一个年份的区间。
 */
function markAreaFor(line: TrendLine): { silent: boolean; data: MarkAreaPair[] } {
  const cutoff = revealCutoff.value
  const withinCutoff = (year: number): boolean =>
    cutoff === null || props.years.indexOf(year) <= cutoff
  // 文字只标在每个系列的第一个同名区间上：每个年份都写一遍会在图顶挤成一排
  const missingAreas: MarkAreaPair[] = (line.missingYears ?? [])
    .filter(withinCutoff)
    .map((year, areaIndex) => [
      {
        xAxis: String(year),
        itemStyle: { color: 'rgba(148, 163, 184, 0.18)' },
        label:
          areaIndex === 0
            ? { show: true, color: '#94a3b8', fontSize: 10, formatter: '无数据' }
            : { show: false },
      },
      { xAxis: String(year) },
    ])
  const absentAreas: MarkAreaPair[] = (line.absentYears ?? [])
    .filter(withinCutoff)
    .map((year, areaIndex) => [
      {
        xAxis: String(year),
        itemStyle: { color: 'rgba(203, 213, 225, 0.10)' },
        label:
          areaIndex === 0
            ? { show: true, color: '#cbd5e1', fontSize: 10, formatter: '该届不举办' }
            : { show: false },
      },
      { xAxis: String(year) },
    ])
  return { silent: true, data: [...missingAreas, ...absentAreas] }
}

/** 播放头位置（像素）：首尾年份在绘图区边缘，中间按序号线性插值 */
const playheadX = computed<number | null>(() => {
  const index = yearIndex.value
  const count = props.years.length
  if (index < 0 || count < 2 || plotWidth.value <= 0) return null
  const usable = plotWidth.value - GRID.left - GRID.right
  if (usable <= 0) return null
  return GRID.left + (index * usable) / (count - 1)
})

const playheadStyle = computed(() => {
  const x = playheadX.value
  if (x === null) return { display: 'none' }
  return {
    transform: `translateX(${x}px)`,
    top: `${GRID.top}px`,
    bottom: `${GRID.bottom}px`,
  }
})

/** 半透明叠加：设计令牌是 #rrggbb，canvas 与 CSS 都需要带 alpha 的颜色 */
function withAlpha(color: string, alpha: number): string {
  const hex = /^#([0-9a-fA-F]{6})$/.exec(color.trim())
  if (!hex) return color
  const value = Number.parseInt(hex[1] as string, 16)
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`
}

/** 数据层 option：只在年份轴或系列变化时重建（setOption 走 notMerge） */
function buildOption(): ChartOption {
  return {
    animation: !reducedMotion.value,
    animationDuration: 640,
    animationEasing: 'cubicOut',
    animationDurationUpdate: 520,
    animationEasingUpdate: 'cubicOut',
    grid: {
      left: GRID.left,
      right: GRID.right,
      top: GRID.top,
      bottom: GRID.bottom,
      containLabel: false,
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      // 两种"空"要分开：播放中尚未绘制 vs 库里确实没有该年份的数据
      valueFormatter: (value, dataIndex) => {
        if (value !== null && value !== undefined) return String(value)
        const cutoff = revealCutoff.value
        return cutoff !== null && dataIndex > cutoff ? '尚未绘制' : '无数据'
      },
    },
    legend: {
      show: false, // 图例由页面头部统一渲染（与会议图例一致）
    },
    xAxis: {
      type: 'category',
      data: props.years.map((year) => String(year)),
      boundaryGap: false,
      axisLabel: { color: '#64748b' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: props.unit,
      nameTextStyle: { color: '#64748b', align: 'left' },
      axisLabel: { color: '#64748b' },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      // 占比类数值固定从 0 起，避免视觉放大差异；上限留给 ECharts 自适应
      min: 0,
    },
    series: props.lines.map((line) => {
      // 两类缺失分别画区间：真缺口用灰色 + 「无数据」，不举办的届用更浅的色 + 「该届不举办」
      const hasRealGap = (line.missingYears ?? []).length > 0
      const color = resolveCssColor(line.color)
      return {
        id: line.key,
        name: line.label,
        type: 'line',
        // 连线与断开：不举办、范围外的空档都跨过（不伪造数据点）；
        // 只有「范围内该届没采到数据」才断开，让缺口在图上看得见
        connectNulls: hasRealGap === false,
        data: pointData(line),
        symbol: 'circle',
        smooth: false,
        itemStyle: { color },
        lineStyle: {
          color,
          width: 2,
          type: line.lineType,
          // 轻投影让曲线从网格里"浮"起来一点，颜色跟随系列色
          shadowBlur: 6,
          shadowColor: withAlpha(color, 0.28),
          shadowOffsetY: 3,
        },
        emphasis: { focus: 'series' },
        markArea: markAreaFor(line),
      }
    }),
  }
}

/**
 * 年份层：只更新随年份变化的部分（逐点数据、当前年份的放大点、区间标注），
 * 用合并更新而不是整图重建，这样 ECharts 的过渡状态保留，曲线是"长出来"而不是"重画一次"。
 * 播放推进、暂停、点年份格都会走这里。
 */
function applyYearLayer(): void {
  if (!chart.value) return
  const series = props.lines.map((line) => ({
    id: line.key,
    data: pointData(line),
    markArea: markAreaFor(line),
  }))
  chart.value.setOption({ series }, { notMerge: false, lazyUpdate: true, silent: true })
}

let resizePending = false

function onResize(): void {
  if (resizePending) return
  resizePending = true
  // 定时回调而不是 requestAnimationFrame：渲染暂停时 rAF 不会到来，
  // 画布会停在旧尺寸（图谱组件里有同样的处理与说明）
  setTimeout(() => {
    resizePending = false
    const element = chartHost.value
    if (!element || !chart.value) return
    if (!element.clientWidth || !element.clientHeight) return
    chart.value.resize()
    plotWidth.value = element.clientWidth
  }, 16)
}

function render(): void {
  if (!chart.value) return
  chart.value.setOption(buildOption(), true)
  plotWidth.value = chartHost.value?.clientWidth ?? 0
  onResize()
}

onMounted(() => {
  if (!chartHost.value) return
  reducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  chart.value = echarts.init(chartHost.value, undefined, { renderer: 'canvas' })
  chart.value.on('click', (params: unknown) => {
    const item = params as { componentType?: string; name?: string }
    if (item.componentType !== 'series') return
    const year = Number(item.name)
    if (Number.isFinite(year)) emit('selectYear', year)
  })
  render()
  resizeObserver = new ResizeObserver(onResize)
  // 观察外层容器：它带着固定高度，宿主是它的 100% 子节点
  if (container.value) resizeObserver.observe(container.value)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', onResize)
  chart.value?.dispose()
  chart.value = null
})

// 数据变化：整图重建（新的年份轴与系列）
watch(() => [props.lines, props.years, props.unit], render)
// 年份或播放状态变化：只更新年份层，不重建图表
// （整图重建会重置 ECharts 的过渡状态，看起来是"跳格"；播放时还要靠合并更新让曲线逐年生长）
watch(() => [props.currentYear, props.playing], applyYearLayer)

/**
 * 供页面导出 GIF 使用：导出要拿到图表画布与播放头当前位置。
 * 由组件给出而不是让页面去 querySelector——画布是 ECharts 内部创建的节点，
 * 外部按选择器取会随实现细节变化而失效（本组件就改过一次宿主结构）。
 */
defineExpose({
  getChartCanvas: (): HTMLCanvasElement | null =>
    chartHost.value?.querySelector('canvas') ?? null,
  getPlayheadX: (): number | null => playheadX.value,
})
</script>

<template>
  <div ref="container" class="trend-canvas" :style="{ height }">
    <!--
      ECharts 有自己的宿主 div：它会在自己的容器里插 DOM，
      如果直接挂在 Vue 管理的这个 div 上，两边都会往同一处插入子节点，
      Vue 的 patch 会与 ECharts 的插入互相覆盖（实测表现为播放头节点被替换成空 div）。
    -->
    <div ref="chartHost" class="chart-host"></div>
    <!--
      播放头：绝对定位覆盖层，靠 CSS transform 过渡滑行。
      pointer-events: none 保证它不挡住曲线的点击选年。
    -->
    <div
      v-if="playheadX !== null"
      class="playhead"
      :class="{ 'is-playing': playing && !reducedMotion }"
      :style="playheadStyle"
      aria-hidden="true"
    >
      <span class="playhead-band"></span>
      <span class="playhead-line"></span>
      <span class="playhead-dot"></span>
      <span class="playhead-label">{{ currentYear }}</span>
    </div>
  </div>
</template>

<style scoped>
.trend-canvas {
  position: relative;
  width: 100%;
  min-height: 260px;
}

/* ECharts 宿主：铺满外层容器，图表尺寸由它决定 */
.chart-host {
  width: 100%;
  height: 100%;
}

.playhead {
  position: absolute;
  left: 0;
  width: 0;
  /* 必须在 canvas 之上：ECharts 的容器是挂载后才插进来的，DOM 顺序不保证，靠层级压住 */
  z-index: 2;
  pointer-events: none;
  /* 滑行：用过渡而不是逐帧，曲线本身不动，只有游标在走 */
  transition: transform v-bind(playheadSlide) cubic-bezier(0.33, 0.75, 0.35, 1);
  will-change: transform;
}

.playhead-band {
  position: absolute;
  bottom: 0;
  left: -17px;
  width: 34px;
  height: 100%;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    180deg,
    rgb(29 78 216 / 10%) 0%,
    rgb(29 78 216 / 4%) 55%,
    rgb(29 78 216 / 0%) 100%
  );
}

.playhead-line {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  border-left: 1px dashed var(--color-primary);
  opacity: 0.75;
}

.playhead-dot {
  position: absolute;
  top: -3px;
  left: -3.5px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 0 3px rgb(29 78 216 / 14%);
}

.playhead-label {
  position: absolute;
  top: -18px;
  left: 0;
  transform: translateX(-50%);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

/* 播放中：游标圆点呼吸 + 光带轻微明暗，提示"时间在走" */
.playhead.is-playing .playhead-dot {
  animation: playhead-pulse 900ms ease-in-out infinite;
}

.playhead.is-playing .playhead-band {
  animation: playhead-band 900ms ease-in-out infinite;
}

@keyframes playhead-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 3px rgb(29 78 216 / 14%);
  }

  50% {
    box-shadow: 0 0 0 7px rgb(29 78 216 / 6%);
  }
}

@keyframes playhead-band {
  0%,
  100% {
    opacity: 0.75;
  }

  50% {
    opacity: 1;
  }
}

/* 用户要求减少动效时：不滑行、不呼吸，游标直接落到目标年份 */
@media (prefers-reduced-motion: reduce) {
  .playhead {
    transition: none;
  }

  .playhead.is-playing .playhead-dot,
  .playhead.is-playing .playhead-band {
    animation: none;
  }
}
</style>
