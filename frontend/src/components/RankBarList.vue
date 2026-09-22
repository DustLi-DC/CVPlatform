<script setup lang="ts">
/**
 * 榜单条目（Top 10 与年度 Top 10 演变共用）。
 * 原型的榜单是 HTML/CSS 实现，不使用图表库；条形宽度按当前列表最大值归一。
 *
 * 动画（本轮改造）：
 * - **排名变化用 FLIP 过渡**：`TransitionGroup` 让行在位次互换时平移过去，而不是瞬间跳位——
 *   「年度 Top 10 演变」里每年推进都会重排，这一项是页面上最明显的动效；
 * - 条形宽度与排序用同一时长过渡，两个动作同步完成；
 * - 计数用 `AnimatedNumber` 补间，年份切换时数字是"走"过去的；
 * - **顺带修掉一个真实缺陷**：`maxCount` 原来是在 setup 里读一次 props 得到的普通常量，
 *   不随数据变化——榜单更新后归一化基准还停在上一次，条长会与实际占比不符。
 *   这里改成 `computed`，随 items 重算。
 */
import { computed } from 'vue'

import AnimatedNumber from './AnimatedNumber.vue'

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

/** 归一化基准必须随数据重算：写成普通常量会让榜单更新后条长失真 */
const maxCount = computed(() => Math.max(...props.items.map((item) => item.count), 1))

function barWidth(count: number): string {
  const ratio = Math.round((count / maxCount.value) * 100)
  return `${Math.max(props.minBarPercent, ratio)}%`
}

function onSelect(item: RankItem): void {
  if (!props.interactive) return
  emit('select', item)
}
</script>

<template>
  <TransitionGroup tag="ol" name="rank" class="rank-list">
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
            <span class="rank-count">
              <AnimatedNumber :value="item.count" /> {{ unit }}
            </span>
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
  </TransitionGroup>
</template>

<style scoped>
.rank-list {
  position: relative;
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
  /* 与行的位移用同一时长与缓动，宽度和排序同时收尾 */
  transition:
    width 520ms cubic-bezier(0.22, 0.61, 0.36, 1),
    background-color 300ms ease;
}

/* 位次互换：整行平移过去（FLIP），而不是瞬间跳位 */
.rank-move {
  transition: transform 520ms cubic-bezier(0.22, 0.61, 0.36, 1);
}

.rank-enter-active,
.rank-leave-active {
  transition:
    opacity 280ms ease,
    transform 280ms ease;
}

.rank-enter-from,
.rank-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (prefers-reduced-motion: reduce) {
  .rank-bar,
  .rank-move,
  .rank-enter-active,
  .rank-leave-active {
    transition: none;
  }
}
</style>
