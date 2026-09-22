<script setup lang="ts">
import { computed } from 'vue'

import {
  displayStatusLabels,
  keywordStatusLabels,
  type DisplayStatus,
  type KeywordStatus,
} from '../types/paper'

const props = withDefaults(
  defineProps<{
    /** 数据完整性徽标 */
    display?: DisplayStatus
    /** 关键词处理状态徽标；“已处理”且无关键词时由调用方传 empty */
    keyword?: KeywordStatus | 'empty'
  }>(),
  {},
)

const displayClass = computed(() => {
  switch (props.display) {
    case 'complete':
      return 'badge-ok'
    case 'review':
      return 'badge-warn'
    case 'failed':
      return 'badge-danger'
    default:
      return 'badge-neutral'
  }
})

const keywordClass = computed(() => {
  switch (props.keyword) {
    case 'done':
      return 'badge-ok'
    case 'running':
    case 'pending':
      return 'badge-warn'
    case 'failed':
      return 'badge-danger'
    default:
      return 'badge-neutral'
  }
})

const displayText = computed(() =>
  props.display ? displayStatusLabels[props.display] : '',
)

const keywordText = computed(() => {
  if (!props.keyword) return ''
  if (props.keyword === 'empty') return '已处理·空'
  return keywordStatusLabels[props.keyword]
})
</script>

<template>
  <span class="status-group">
    <span v-if="display" class="badge" :class="displayClass">{{ displayText }}</span>
    <span v-if="keyword" class="badge" :class="keywordClass">{{ keywordText }}</span>
  </span>
</template>

<style scoped>
.status-group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
