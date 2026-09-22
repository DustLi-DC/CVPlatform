<script setup lang="ts">
/**
 * 关键词关系图谱（ECharts graph + force 布局），按原型规范渲染：
 *
 * - 节点大小 `14 + √count × 1.8`，`count = 0` 时固定 10（与原型一致）；
 * - 节点颜色按主题分组，未分组用中性色；
 * - 边宽 `1 + 共现论文数 / 40`；只画两端都在节点集合内的边（由接口保证）；
 * - 力导向布局、允许拖拽与缩放漫游，标签自动避让（labelLayout.hideOverlap）；
 * - 节点上限与最小共现由调用方传入，展示范围在调用方的图例处标注。
 *
 * 生命周期：容器尺寸变化用 ResizeObserver 跟随，组件卸载时移除监听并 dispose 实例，
 * 避免切换页面后残留实例继续占用内存与动画帧。
 *
 * 依赖按需注册：只引入 graph 图表、提示框与 canvas 渲染器，不整包引入 ECharts。
 * 整包会让产物从十几 kB 涨到 400 kB 以上，对 2 Mbps 的部署环境是明显浪费；
 * 阶段 9 的趋势图在这里追加注册折线图与相应组件即可。
 */
import { GraphChart } from 'echarts/charts'
import type { ComposeOption } from 'echarts/core'
import { TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { LabelLayout } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import type { GraphSeriesOption } from 'echarts/charts'
import type { TooltipComponentOption } from 'echarts/components'

import type { GraphEdge, GraphNode } from '../types/stats'
import { groupColor } from '../types/stats'

echarts.use([GraphChart, TooltipComponent, LabelLayout, CanvasRenderer])

const props = withDefaults(
  defineProps<{
    nodes: GraphNode[]
    edges: GraphEdge[]
    height?: string
  }>(),
  { height: '430px' },
)

const emit = defineEmits<{
  select: [node: GraphNode]
}>()

const container = ref<HTMLDivElement | null>(null)
/** ECharts 实例不适合放进响应式代理（会深层代理内部对象），用 shallowRef */
const chart = shallowRef<echarts.ECharts | null>(null)
let resizeObserver: ResizeObserver | null = null

/** 节点半径：与原型同一公式，避免图形语义与原型不一致 */
function nodeSize(count: number): number {
  if (count <= 0) return 10
  return 14 + Math.sqrt(count) * 1.8
}

/** 边宽：与原型同一公式（1 + 共现论文数 / 40） */
function edgeWidth(weight: number): number {
  return 1 + weight / 40
}

function readColor(variable: string): string {
  // 分组色以 CSS 变量存放（与全站主题一致），画到 canvas 前解析成具体颜色值
  const value = getComputedStyle(document.documentElement).getPropertyValue(variable).trim()
  return value || '#94a3b8'
}

function colorFor(group: string | null): string {
  const variable = groupColor(group)
  if (variable.startsWith('var(')) {
    return readColor(variable.slice(4, -1))
  }
  return variable
}

/** 只组合本组件实际用到的图表与组件类型 */
type ChartOption = ComposeOption<GraphSeriesOption | TooltipComponentOption>

function buildOption(): ChartOption {
  // 只画两端都在节点集合内的边：接口已按节点上限过滤，这里再兜一次底
  const nodeNames = new Set(props.nodes.map((node) => node.key))

  return {
    tooltip: {
      confine: true,
      formatter: (params: unknown) => {
        const item = params as { dataType?: string; data?: Record<string, unknown> }
        if (item.dataType === 'edge') {
          const data = item.data as { source_name?: string; target_name?: string; weight?: number }
          return `${data.source_name} — ${data.target_name}<br/>共现论文数：${data.weight} 篇`
        }
        const data = item.data as { name?: string; count?: number; group_label?: string }
        return `${data.name}<br/>相关论文：${data.count} 篇<br/>分组：${data.group_label ?? '未分组'}`
      },
    },
    animationDuration: 600,
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        // 允许拖动节点，也保留缩放与平移（真实数据节点比原型多，需要漫游）
        force: {
          // 圆形初始布局 + 关掉布局动画：力导向布局一次性算完再渲染。
          // 开着动画时节点位置靠逐帧迭代收敛，页面渲染被暂停（后台标签页、低功耗模式）
          // 就会停在初始的紧凑状态；一次性布局在任何情况下都是同一张可读的图。
          initLayout: 'circular',
          layoutAnimation: false,
          repulsion: 420,
          edgeLength: [90, 220],
          gravity: 0.05,
          friction: 0.5,
        },
        label: {
          show: true,
          position: 'right',
          fontSize: 11,
          color: '#334155',
          formatter: '{b}',
        },
        labelLayout: { hideOverlap: true },
        lineStyle: { color: '#cbd5e1', curveness: 0.08, opacity: 0.9 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        data: props.nodes.map((node) => ({
          name: node.key,
          // 名称另存：key 是查询用标识，标签与提示显示 name
          value: node.count,
          symbolSize: nodeSize(node.count),
          itemStyle: { color: colorFor(node.group) },
          count: node.count,
          group_label: node.group,
          display_name: node.name,
          label: { formatter: node.name },
        })),
        links: props.edges
          .filter((edge) => nodeNames.has(edge.source) && nodeNames.has(edge.target))
          .map((edge) => ({
            source: edge.source,
            target: edge.target,
            weight: edge.weight,
            source_name: edge.source_name,
            target_name: edge.target_name,
            lineStyle: { width: edgeWidth(edge.weight) },
          })),
      },
    ],
  }
}

function render(): void {
  if (!chart.value) return
  // 数据变化时整体重设：节点集合变化后旧布局无意义，notMerge 避免残留旧节点
  chart.value.setOption(buildOption(), true)
  // 重设后按当前容器尺寸校正一次：侧栏折叠、窗口变化等会让初始尺寸失效
  onResize()
}

/**
 * 尺寸校正：合并到一次定时回调里执行，避免连续变化时反复重排。
 *
 * 用 setTimeout 而不是 requestAnimationFrame：rAF 只在页面被渲染时触发，
 * 标签页不可见或渲染被暂停时它不会到来，画布就会一直停在旧尺寸（实测复现过）。
 * 定时回调在后台标签页里只会被节流，仍会执行，因此更可靠。
 */
let resizePending = false

function onResize(): void {
  if (resizePending) return
  resizePending = true
  setTimeout(() => {
    resizePending = false
    const element = container.value
    if (!element || !chart.value) return
    // 容器不可见时尺寸为 0，此时跳过，避免把画布压成 0×0
    if (!element.clientWidth || !element.clientHeight) return
    chart.value.resize()
  }, 16)
}

onMounted(() => {
  if (!container.value) return
  chart.value = echarts.init(container.value, undefined, { renderer: 'canvas' })
  chart.value.on('click', (params: unknown) => {
    const item = params as { dataType?: string; data?: { name?: string } }
    if (item.dataType !== 'node') return
    const key = item.data?.name
    const node = props.nodes.find((entry) => entry.key === key)
    if (node) emit('select', node)
  })
  render()
  // 两种监听都装：ResizeObserver 覆盖容器级变化（侧栏、栅格），
  // window.resize 覆盖视口级变化且在后台标签页被节流时仍会触发
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

// 节点或边变化时重绘（父组件在筛选变化后传入新数据）
watch(() => [props.nodes, props.edges], render)
</script>

<template>
  <div ref="container" class="graph-canvas" :style="{ height }"></div>
</template>

<style scoped>
.graph-canvas {
  width: 100%;
  min-height: 260px;
}
</style>
