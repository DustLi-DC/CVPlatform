<script setup lang="ts">
/**
 * 演示数据/边界说明提示条。
 * 用途一：标注页面数值来自演示数据（tone="warn"）。
 * 用途二：说明某项操作尚未接入后端（tone="info"）。
 */
withDefaults(
  defineProps<{
    tone?: 'info' | 'warn' | 'neutral'
    title?: string
  }>(),
  { tone: 'warn', title: '' },
)
</script>

<template>
  <div class="notice" :class="`notice-${tone}`">
    <span class="notice-mark" aria-hidden="true">!</span>
    <span class="notice-text">
      <strong v-if="title">{{ title }}：</strong><slot />
    </span>
  </div>
</template>

<style scoped>
.notice-mark {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border-radius: 50%;
  background: currentcolor;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}

.notice-text {
  line-height: 1.6;
}
</style>
