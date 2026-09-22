<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  pages: number
  total: number
  /** 每页条数说明文案，如“每页 8 条” */
  pageSizeHint: string
}>()

const emit = defineEmits<{
  'update:page': [value: number]
}>()

/** 页数较多时收敛为窗口页码，避免按钮过多导致换行溢出 */
const visiblePages = computed(() => {
  const { page, pages } = props
  if (pages <= 7) {
    return Array.from({ length: pages }, (_, index) => index + 1)
  }
  const windowStart = Math.max(1, Math.min(page - 2, pages - 4))
  return Array.from({ length: 5 }, (_, index) => windowStart + index)
})

function go(target: number): void {
  if (target < 1 || target > props.pages || target === props.page) return
  emit('update:page', target)
}
</script>

<template>
  <div class="pager-bar">
    <span class="pager-hint">{{ pageSizeHint }} · 共 {{ total }} 条（演示数据）</span>
    <nav class="pager" aria-label="分页">
      <button
        type="button"
        class="pager-btn"
        :disabled="page === 1"
        @click="go(page - 1)"
      >
        上一页
      </button>
      <button
        v-for="item in visiblePages"
        :key="item"
        type="button"
        class="pager-btn"
        :class="{ 'is-current': item === page }"
        :aria-current="item === page ? 'page' : undefined"
        @click="go(item)"
      >
        {{ item }}
      </button>
      <button
        type="button"
        class="pager-btn"
        :disabled="page === pages"
        @click="go(page + 1)"
      >
        下一页
      </button>
    </nav>
  </div>
</template>

<style scoped>
.pager-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  border-top: 1px solid var(--color-border-soft);
}

.pager-hint {
  font-size: 12px;
  color: var(--color-text-subtle);
}

.pager {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pager-btn {
  padding: 6px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-subtle);
  font-size: 12px;
  cursor: pointer;
}

.pager-btn:hover:not(:disabled) {
  background: var(--color-surface-muted);
}

.pager-btn:disabled {
  border-color: var(--color-border);
  color: var(--color-text-faint);
  cursor: not-allowed;
}

.pager-btn.is-current {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

@media (max-width: 900px) {
  .pager-bar {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
