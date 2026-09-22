<script setup lang="ts">
/**
 * 图表容器。
 *
 * 容器负责标题、副标题、单位、图例、图表区高度与溢出约束，并提供两处插槽：
 * 默认插槽放图表本身（阶段 8 起放 ECharts 实例所在的组件），`tools` 插槽放图表级控件
 * （例如图谱的节点上限与最小共现）。容器本身不引入图表库，也不画占位假图。
 */
withDefaults(
  defineProps<{
    title: string
    subtitle: string
    /** 单位提示，如“单位：%” */
    unit?: string
    /** 图表区高度，原型为 430px（图谱）与 400px（趋势） */
    height?: string
    legend?: { label: string; color: string; shape?: 'dot' | 'line' | 'block' }[]
    /** 占位说明：仅在提供默认占位内容时显示 */
    pendingNote?: string
    /** 容器内可见的当前状态文字，便于验证交互是否生效 */
    statusText?: string
  }>(),
  { unit: '', height: '400px', legend: () => [], statusText: '', pendingNote: '' },
)
</script>

<template>
  <section class="chart-card">
    <div class="chart-head">
      <div>
        <h2 class="card-title">{{ title }}</h2>
        <p class="card-subtitle">{{ subtitle }}</p>
      </div>
      <div class="chart-head-right">
        <slot name="tools" />
        <ul v-if="legend.length" class="chart-legend">
          <li v-for="item in legend" :key="item.label" class="chart-legend-item">
            <span
              class="legend-mark"
              :class="`is-${item.shape ?? 'dot'}`"
              :style="{ background: item.color }"
              aria-hidden="true"
            ></span>
            {{ item.label }}
          </li>
        </ul>
        <span v-if="unit" class="tag">{{ unit }}</span>
      </div>
    </div>

    <div class="chart-slot" :style="{ height }">
      <slot>
        <div class="chart-placeholder">
          <p class="chart-placeholder-title">图表容器已就绪</p>
          <p v-if="statusText" class="chart-placeholder-status">{{ statusText }}</p>
          <p class="chart-placeholder-note">{{ pendingNote }}</p>
        </div>
      </slot>
    </div>

    <div v-if="$slots.footnote" class="chart-footnote">
      <slot name="footnote" />
    </div>
  </section>
</template>

<style scoped>
.chart-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.chart-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--color-border-soft);
}

.chart-head-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 11px;
  color: var(--color-text-subtle);
}

.chart-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-mark {
  display: inline-block;
  background: currentcolor;
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

.chart-slot {
  position: relative;
  width: 100%;
  min-height: 240px;
  /* 图表在窄窗口下不撑破容器 */
  overflow: hidden;
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
  background:
    repeating-linear-gradient(
      45deg,
      var(--color-surface-muted),
      var(--color-surface-muted) 10px,
      var(--color-surface) 10px,
      var(--color-surface) 20px
    );
  text-align: center;
  padding: 16px;
}

.chart-placeholder-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.chart-placeholder-status {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
}

.chart-placeholder-note {
  max-width: 460px;
  font-size: 12px;
  color: var(--color-text-subtle);
  line-height: 1.7;
}

.chart-footnote {
  display: grid;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border-soft);
  font-size: 12px;
  color: var(--color-text-subtle);
}

/* 窄窗口下图表高度与图例收敛 */
@media (max-width: 900px) {
  .chart-head {
    flex-direction: column;
  }

  .chart-head-right {
    justify-content: flex-start;
  }

  .chart-slot {
    height: 300px !important;
  }
}
</style>
