/**
 * ECharts 按需注册（图谱与趋势图共用）。
 *
 * 只引入实际用到的图表与组件，不整包引入：整包会让产物从十几 kB 涨到 400 kB 以上，
 * 对 2 Mbps 的部署环境是明显浪费。两个图表组件都从这里取 `echarts`，
 * 避免各自注册造成「换了组件忘记加注册」的漂移。
 *
 * 用到的能力：
 * - GraphChart：关键词关系图谱（力导向）
 * - LineChart：热度走势曲线（多为空值时用 null 形成断点）
 * - GridComponent / TooltipComponent / LegendComponent / MarkAreaComponent / MarkLineComponent
 * - LabelLayout：标签避让（图谱的 labelLayout.hideOverlap）
 * - CanvasRenderer：canvas 渲染（不引入 SVG 渲染器以减小体积）
 */
import { GraphChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { LabelLayout } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  GraphChart,
  LineChart,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  LabelLayout,
  CanvasRenderer,
])

export { echarts }

/**
 * 颜色解析从本模块转出（实现见 `./colors`）。
 *
 * 放在单独模块是因为 GIF 导出也要用它，而导出不该为了解析一个颜色就把整包 ECharts 拉进来。
 * 这里保留转出，图表组件原有的 `import { resolveCssColor } from '../composables/echarts'` 不受影响。
 */
export { resolveCssColor } from './colors'
