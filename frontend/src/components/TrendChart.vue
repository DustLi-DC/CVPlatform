<script setup lang="ts">
/**
 * 热度走势曲线（ECharts line），按原型规范渲染：
 *
 * - 横轴为年份，纵轴按「占比（%）」或「论文数（篇）」切换，单位在图例与轴名上标明；
 * - 一条曲线 = 一个会议（配色沿用全站会议色）；比较多个主题时用线型区分主题，
 *   颜色始终表示会议，避免两套含义混在同一个视觉通道里；
 * - **没有记录的年份用 null 形成断点**，并在图上画出灰色区间；有样本但计数为 0
 *   的点落在 0 轴上——两种情况必须能区分开（null 与 0 在 ECharts 里画法不同）；
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
  /** 该线在这些年份完全没有记录：画灰色区间，与「计数为 0」区分开 */
  missingYears?: number[]
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
type MarkAreaPair = [
  { xAxis: string; itemStyle?: { color: string }; label?: { show: boolean; color?: string; fontSize?: number } },
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
      // 「无数据」文字只标在第一个区间上：每个缺失年份都写一遍会在图顶挤成一排，
      // 反而看不清；灰色色块本身已经把范围标出来了，具体解释放在图下方说明里
      const missingAreas: MarkAreaPair[] = (line.missingYears ?? []).map((year, areaIndex) => [
        {
          xAxis: String(year),
          itemStyle: { color: 'rgba(148, 163, 184, 0.18)' },
          label: areaIndex === 0 ? { show: true, color: '#94a3b8', fontSize: 10 } : { show: false },
        },
        { xAxis: String(year) },
      ])
      return {
        id: line.key,
        name: line.label,
        type: 'line',
        // null 表示没有记录：断开曲线，不连成直线，也不当作 0
        connectNulls: false,
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
        markArea: missingAreas.length
          ? {
              silent: true,
              data: missingAreas,
              label: { show: true, color: '#94a3b8', fontSize: 10, formatter: '无数据' },
              // 只标注第一个区间（其余区间的 label 在数据里关闭）
            }
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
