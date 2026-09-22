/**
 * 可用年份（来自后端覆盖数据）。
 *
 * 论文列表与新增/编辑表单的年份选项原先是集中管理的演示常量（2022—2025），
 * 覆盖范围变化时会出现「选项里有但库里没有」或反之的偏差。这里改为读取
 * `GET /api/stats/coverage` 的年份轴，接口不可用时退回空列表（调用方自行处理），
 * 不猜测年份范围。
 *
 * 同一次会话内只请求一次：年份轴是低频变化的数据，多个组件共享同一份结果。
 */
import { ref } from 'vue'

import { fetchCoverage } from '../api/statsApi'

const years = ref<number[]>([])
const loaded = ref(false)
const loading = ref(false)
const error = ref('')
let inflight: Promise<void> | null = null

async function load(force = false): Promise<void> {
  if (loaded.value && !force) return
  if (inflight) return inflight
  loading.value = true
  error.value = ''
  inflight = (async () => {
    try {
      const coverage = await fetchCoverage()
      const cells = coverage.covered.map((item) => item.year)
      const targets = coverage.target_conference_years.map((item) => item.year)
      // 覆盖数据与目标范围合并：既要有数据的年份，也要能选到目标年份以便筛选空结果
      years.value = [...new Set([...cells, ...targets])].sort((a, b) => a - b)
      loaded.value = true
    } catch (caught) {
      error.value = '年份范围加载失败，可先直接检索；刷新页面后重试。'
      console.error('加载年份范围失败：', caught)
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

export function useAvailableYears() {
  return { years, loaded, loading, error, load }
}
