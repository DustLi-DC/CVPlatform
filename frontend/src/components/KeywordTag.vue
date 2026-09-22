<script setup lang="ts">
import { computed } from 'vue'

import { findDemoTopic, topicGroupColors } from '../demo/topics'
import type { PaperKeyword } from '../types/paper'

const props = withDefaults(
  defineProps<{
    name: string
    /** 关键词来源：作者提供或系统提取，两者在界面分开展示 */
    origin?: PaperKeyword['origin']
    /** 主题名；未归类时显示“未归类”标记 */
    topic?: string | null
    /** 是否可点击（可点击时用于按关键词筛选论文） */
    interactive?: boolean
  }>(),
  { origin: 'system', topic: null, interactive: true },
)

const dotColor = computed(() => {
  if (!props.topic) return topicGroupColors.none
  const topic = findDemoTopic(props.topic)
  return topic ? topicGroupColors[topic.group] : topicGroupColors.none
})

const isMapped = computed(() => Boolean(props.topic))
</script>

<template>
  <component
    :is="interactive ? 'button' : 'span'"
    class="keyword-tag"
    :class="[`is-${origin}`, { 'is-unmapped': !isMapped }]"
    :type="interactive ? 'button' : undefined"
    :title="isMapped ? `主题：${topic}` : '未归类到任何主题'"
  >
    <span class="keyword-dot" :style="{ background: dotColor }" aria-hidden="true"></span>
    {{ name }}
    <span v-if="!isMapped" class="keyword-flag">未归类</span>
  </component>
</template>

<style scoped>
.keyword-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--color-neutral-bg);
  color: var(--color-text-muted);
  font-size: 11px;
  cursor: default;
}

/* 信息提取来源不同，用描边区分：作者关键词为虚线边框 */
.keyword-tag.is-author {
  border-color: var(--color-border-strong);
  border-style: dashed;
  background: var(--color-surface);
}

.keyword-tag.is-unmapped {
  background: var(--color-surface-muted);
  color: var(--color-text-faint);
}

button.keyword-tag {
  cursor: pointer;
}

button.keyword-tag:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.keyword-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: 0 0 auto;
}

.keyword-flag {
  font-size: 10px;
  color: var(--color-text-faint);
}
</style>
