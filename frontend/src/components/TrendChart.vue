<script setup lang="ts">
/**
 * 热度走势曲线（ECharts line），按原型规范渲染：
 *
 * - 横轴为年份，纵轴按「占比（%）」或「论文数（篇）」切换，单位在图例与轴名上标明；
 * - 一条曲线 = 一个会议（配色沿用全站会议色）；比较多个主题时用线型区分主题，
 *   颜色始终表示会议，避免两套含义混在同一个视觉通道里；
 * - 缺失分两种，画法不同：
 *   1) **该届不举办**（ICCV 偶数年、ECCV 奇数年）：画浅色区间并标注「该届不举办」，
 *      曲线**跨过该年份连线**——这不是数据缺口，断开会让读者以为是采集缺失；
 *   2) **该届没有采到数据**：画灰色区间并标注「无数据」，曲线**断开**，不跨过；
 * - 有样本但计数为 0 的点落在 0 轴上——与上面两种情况都不同（null 与 0 在 ECharts 里画法不同）；
 * - 当前年份用虚线标注，播放时随年份前移；
 * - 点击曲线数据点或年份区间可跳转到该年份（emit selectYear）。
 *
 * 生命周期：容器尺寸变化跟随（ResizeObserver + window.resize，回调走定时器，
 * 页面渲染暂停时 rAF 不会触发），组件卸载时移除监听并 dispose 实例。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import { echarts, resolveCssColor } from '../composables/echarts'
import type { ComposeOption } from 'echarts/core'
import type { LineSeriesOption } from 'echarts/charts'
import type {
  GridComponentOption,
  LegendComponentOption,
  MarkAreaComponentOption,
  MarkLineComponentOption,
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
    /** 当前年份：画虚线定位 */
    currentYear: number | null
    height?: string
    /** 数值提示里的额外说明，如「分母」来源 */
    valueLabel?: string
  }>(),
  { height: '400px', valueLabel: '值', currentYear: null },
)

const emit = defineEmits<{
  selectYear: [year: number]
}>()

const container = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
let resizeObserver: ResizeObserver | null = null

type ChartOption = ComposeOption<
  | LineSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | MarkAreaComponentOption
  | MarkLineComponentOption
  | TooltipComponentOption
>

/** markArea 的两维元组类型：需要恰好两个端点，写成元组才能满足 ECharts 的类型 */
type MarkAreaLabel = { show: boolean; color?: string; fontSize?: number; formatter?: string }

type MarkAreaPair = [
  { xAxis: string; itemStyle?: { color: string }; label?: MarkAreaLabel },
  { xAxis: string },
]

function buildOption(): ChartOption {

  return {
    grid: { left: 56, right: 24, top: 48, bottom: 36, containLabel: false },
    tooltip: {
      trigger: 'axis',
      confine: true,
      valueFormatter: (value) => (value === null || value === undefined ? '无数据' : String(value)),
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
    series: props.lines.map((line, index) => {
      // 两类缺失分别画区间：真缺口用灰色 + 「无数据」，不举办的届用更浅的色 + 「该届不举办」。
      // 文字只标在每个系列的第一个同名区间上：每个年份都写一遍会在图顶挤成一排。
      const hasRealGap = (line.missingYears ?? []).length > 0
      const missingAreas: MarkAreaPair[] = (line.missingYears ?? []).map((year, areaIndex) => [
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
      const absentAreas: MarkAreaPair[] = (line.absentYears ?? []).map((year, areaIndex) => [
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
      return {
        id: line.key,
        name: line.label,
        type: 'line',
        // 真缺口必须断开；只有「该届不举办」造成的空档才跨过连线（不伪造数据点）
        connectNulls: hasRealGap === false,
        data: line.values,
        symbol: 'circle',
        symbolSize: 7,
        smooth: false,
        itemStyle: { color: resolveCssColor(line.color) },
        lineStyle: {
          color: resolveCssColor(line.color),
          width: 2,
          type: line.lineType,
        },
        emphasis: { focus: 'series' },
        markArea:
          missingAreas.length || absentAreas.length
            ? { silent: true, data: [...missingAreas, ...absentAreas] }
            : undefined,
        markLine:
          index === 0 && props.currentYear !== null
            ? {
                silent: true,
                symbol: 'none',
                lineStyle: { color: '#1d4ed8', type: 'dashed', width: 1 },
                label: {
                  formatter: `${props.currentYear}`,
                  color: '#1d4ed8',
                  fontSize: 11,
                  // 标在虚线上端靠内一侧：靠左会与纵轴名称「占比（%）」叠在一起
                  position: 'insideEndTop',
                },
                data: [{ xAxis: String(props.currentYear) }],
              }
            : undefined,
      }
    }),
  }
}

let resizePending = false

function onResize(): void {
  if (resizePending) return
  resizePending = true
  // 定时回调而不是 requestAnimationFrame：渲染暂停时 rAF 不会到来，
  // 画布会停在旧尺寸（图谱组件里有同样的处理与说明）
  setTimeout(() => {
    resizePending = false
    const element = container.value
    if (!element || !chart.value) return
    if (!element.clientWidth || !element.clientHeight) return
    chart.value.resize()
  }, 16)
}

function render(): void {
  if (!chart.value) return
  chart.value.setOption(buildOption(), true)
  onResize()
}

onMounted(() => {
  if (!container.value) return
  chart.value = echarts.init(container.value, undefined, { renderer: 'canvas' })
  chart.value.on('click', (params: unknown) => {
    const item = params as { componentType?: string; name?: string }
    if (item.componentType !== 'series') return
    const year = Number(item.name)
    if (Number.isFinite(year)) emit('selectYear', year)
  })
  render()
  resizeObserver = new ResizeObserver(onResize)
  resizeObserver.observe(container.value)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', onResize)
  chart.value?.dispose()
  chart.value = null
})

watch(() => [props.lines, props.years, props.currentYear], render)
</script>

<template>
  <div ref="container" class="trend-canvas" :style="{ height }"></div>
</template>

<style scoped>
.trend-canvas {
  width: 100%;
  min-height: 260px;
}
</style>
