<script setup lang="ts">
/**
 * 榜单条目（Top 10 与年度 Top 10 演变共用）。
 * 原型的榜单是 HTML/CSS 实现，不使用图表库；条形宽度按当前列表最大值归一。
 */
export interface RankItem {
  key: string
  label: string
  count: number
  color: string
  /** 是否高亮（例如当前在抽屉中查看的主题） */
  active?: boolean
}

const props = withDefaults(
  defineProps<{
    items: RankItem[]
    /** 数值单位后缀 */
    unit?: string
    /** 条形最小宽度百分比，原型为 6% */
    minBarPercent?: number
    interactive?: boolean
    /** 数量为 0 时是否仍然展示（有样本但主题不存在的情形，落在 0 轴） */
    showZero?: boolean
  }>(),
  { unit: '篇', minBarPercent: 6, interactive: true, showZero: true },
)

const emit = defineEmits<{
  select: [item: RankItem]
}>()

const maxCount = Math.max(...props.items.map((item) => item.count), 1)

function barWidth(count: number): string {
  const ratio = Math.round((count / maxCount) * 100)
  return `${Math.max(props.minBarPercent, ratio)}%`
}

function onSelect(item: RankItem): void {
  if (!props.interactive) return
  emit('select', item)
}
</script>

<template>
  <ol class="rank-list">
    <li v-for="(item, index) in items" :key="item.key">
      <component
        :is="interactive ? 'button' : 'div'"
        class="rank-row"
        :class="{ 'is-active': item.active }"
        :type="interactive ? 'button' : undefined"
        @click="onSelect(item)"
      >
        <span class="rank-index" :class="{ 'is-top': index < 3 }">{{ index + 1 }}</span>
        <span class="rank-main">
          <span class="rank-line">
            <span class="rank-label">{{ item.label }}</span>
            <span class="rank-count">{{ item.count }} {{ unit }}</span>
          </span>
          <span class="rank-track">
            <span
              class="rank-bar"
              :style="{ width: barWidth(item.count), background: item.color }"
            ></span>
          </span>
        </span>
      </component>
    </li>
  </ol>
</template>

<style scoped>
.rank-list {
  padding: 8px 12px;
}

.rank-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  text-align: left;
}

button.rank-row {
  cursor: pointer;
}

button.rank-row:hover {
  background: var(--color-surface-muted);
}

.rank-row.is-active {
  background: var(--color-primary-soft);
}

.rank-index {
  width: 24px;
  flex: 0 0 auto;
  color: var(--color-text-faint);
  font-size: 14px;
  font-weight: 700;
  text-align: center;
}

.rank-index.is-top {
  color: var(--color-primary);
}

.rank-main {
  flex: 1;
  min-width: 0;
}

.rank-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.rank-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rank-count {
  flex: 0 0 auto;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.rank-track {
  display: block;
  height: 8px;
  margin-top: 8px;
  border-radius: 999px;
  background: var(--color-neutral-bg);
  overflow: hidden;
}

.rank-bar {
  display: block;
  height: 8px;
  border-radius: 999px;
}
</style>
