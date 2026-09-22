<script setup lang="ts">
const props = defineProps<{
  label: string
  value: string
  hint: string
}>()

/** 数值旁统一标注演示来源，避免与真实统计混淆 */
const isDemo = props.hint.includes('演示')
</script>

<template>
  <div class="card stat-card">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value">{{ value }}</div>
    <div class="stat-hint" :class="{ 'is-demo': isDemo }">{{ hint }}</div>
  </div>
</template>

<style scoped>
.stat-card {
  padding: 16px 20px;
}

.stat-label {
  font-size: 12px;
  color: var(--color-text-subtle);
}

.stat-value {
  margin-top: 8px;
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text-strong);
}

.stat-hint {
  margin-top: 4px;
  font-size: 11px;
  color: var(--color-text-faint);
}

/* 演示数据来源用琥珀色标出，与真实统计区分 */
.stat-hint.is-demo {
  color: var(--color-warn-text);
}
</style>
