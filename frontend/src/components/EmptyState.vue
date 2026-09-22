<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    description?: string
    /** 是否渲染在虚线卡片内（用于结果区占位） */
    boxed?: boolean
  }>(),
  { description: '', boxed: false },
)
</script>

<template>
  <div class="empty-state" :class="{ 'is-boxed': boxed }">
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  padding: 40px 24px;
  text-align: center;
}

.empty-state.is-boxed {
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.empty-desc {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-faint);
  line-height: 1.7;
}

.empty-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
  margin-top: 20px;
}
</style>
