<script setup lang="ts">
/**
 * 关键词关系图谱（ECharts graph + force 布局），按原型规范渲染：
 *
 * - **节点大小按当前数据范围归一**：`14 + 22 × √(count / 最大count)`（14–36 px），
 *   `count = 0` 时固定 10。原型用的是绝对公式 `14 + √count × 1.8`，那在 1,200 篇样本上
 *   直径约 10–46 px 是合适的；但语料扩到 2.9 万篇后最大 count 达 7,546，
 *   绝对公式会给出 170 px 的圆，四十个这样的圆无法布局、标签全部互相覆盖。
 *   归一化保留了「越大表示相关论文越多」的编码方向，具体篇数在提示框与侧栏给出。
 * - 边宽同样按范围归一：`1 + 5 × √(共现论文数 / 最大权重)`（1–6 px），原因同上
 *   （原型公式 `1 + 权重 / 40` 在最大权重 1,942 时会画出 49 px 的边，图形完全糊掉）；
 * - 节点颜色按主题分组，未分组用中性色；只画两端都在节点集合内的边（由接口保证）；
 * - 力导向布局、允许拖拽与缩放漫游，标签自动避让（labelLayout.hideOverlap）；
 * - 节点上限与最小共现由调用方传入，展示范围在调用方的图例处标注。
 *
 * 生命周期：容器尺寸变化用 ResizeObserver 跟随，组件卸载时移除监听并 dispose 实例，
 * 避免切换页面后残留实例继续占用内存与动画帧。
 *
 * 依赖按需注册集中在 composables/echarts.ts（图谱与趋势图共用），这里只取用实例，
 * 避免各组件各自注册造成「换了组件忘记加注册」的漂移。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import type { GraphSeriesOption } from 'echarts/charts'
import type { TooltipComponentOption } from 'echarts/components'
import type { ComposeOption } from 'echarts/core'

import { echarts, resolveCssColor } from '../composables/echarts'
import type { GraphEdge, GraphNode } from '../types/stats'
import { groupColor } from '../types/stats'

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

/** 节点直径：按当前范围的最大值归一，保持「越大越热」的语义同时保证可读 */
function nodeSize(count: number, maxCount: number): number {
  if (count <= 0) return 10
  const ratio = maxCount > 0 ? count / maxCount : 1
  return 14 + 22 * Math.sqrt(Math.max(0, Math.min(1, ratio)))
}

/** 边宽：同样按最大权重归一（1–6 px） */
function edgeWidth(weight: number, maxWeight: number): number {
  const ratio = maxWeight > 0 ? weight / maxWeight : 1
  return 1 + 5 * Math.sqrt(Math.max(0, Math.min(1, ratio)))
}

function colorFor(group: string | null): string {
  // 分组色以 CSS 变量存放（与全站主题一致），画到 canvas 前必须解析成具体颜色值
  return resolveCssColor(groupColor(group))
}

/** 只组合本组件实际用到的图表与组件类型 */
type ChartOption = ComposeOption<GraphSeriesOption | TooltipComponentOption>

function buildOption(): ChartOption {
  // 只画两端都在节点集合内的边：接口已按节点上限过滤，这里再兜一次底
  const nodeNames = new Set(props.nodes.map((node) => node.key))
  // 归一化的分母：节点按最大关联论文数、边按最大共现论文数
  const maxCount = Math.max(...props.nodes.map((node) => node.count), 1)
  const maxWeight = Math.max(...props.edges.map((edge) => edge.weight), 1)

  return {
    tooltip: {
      confine: true,
      formatter: (params: unknown) => {
        const item = params as { dataType?: string; data?: Record<string, unknown> }
        if (item.dataType === 'edge') {
          const data = item.data as { source_name?: string; target_name?: string; weight?: number }
          return `${data.source_name} — ${data.target_name}<br/>共现论文数：${data.weight} 篇`
        }
        const data = item.data as {
          name?: string
          display_name?: string
          count?: number
          group_label?: string
        }
        // 提示框显示中文主题名（name 是查询用的 slug，展示对读者没有意义）
        return `${data.display_name ?? data.name}<br/>相关论文：${data.count} 篇<br/>分组：${
          data.group_label ?? '未分组'
        }`
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
          // 斥力与边长按节点尺寸量级设定：40 个节点、直径最大 36 px，
          // 需要更大的分离距离才能让标签放得下（实测 1600 时中心仍偏挤）
          repulsion: 3000,
          edgeLength: [110, 260],
          gravity: 0.03,
          friction: 0.7,
        },
        label: {
          show: true,
          position: 'right',
          fontSize: 11,
          color: '#334155',
          formatter: '{b}',
        },
        // 先尝试纵向错位，实在放不下才隐藏：40 个节点的图里直接隐藏会丢掉太多标签
        labelLayout: { moveOverlap: 'shiftY', hideOverlap: true },
        lineStyle: { color: '#cbd5e1', curveness: 0.08, opacity: 0.9 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        data: props.nodes.map((node) => ({
          name: node.key,
          // 名称另存：key 是查询用标识，标签与提示显示 name
          value: node.count,
          symbolSize: nodeSize(node.count, maxCount),
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
            lineStyle: { width: edgeWidth(edge.weight, maxWeight) },
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
