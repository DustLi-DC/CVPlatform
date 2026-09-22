<script setup lang="ts">
import { conferenceColors, type Conference } from '../types/paper'

const props = withDefaults(
  defineProps<{
    modelValue: Conference[]
    label?: string
    /** 至少保留一个选项，与原型行为一致 */
    minSelected?: number
  }>(),
  { label: '会议筛选（可多选）', minSelected: 1 },
)

const emit = defineEmits<{
  'update:modelValue': [value: Conference[]]
}>()

const options: Conference[] = ['CVPR', 'ICCV', 'ECCV']

function toggle(conference: Conference): void {
  const selected = props.modelValue
  if (selected.includes(conference)) {
    if (selected.length <= props.minSelected) return
    emit(
      'update:modelValue',
      selected.filter((item) => item !== conference),
    )
    return
  }
  emit('update:modelValue', [...selected, conference])
}
</script>

<template>
  <fieldset class="chip-field">
    <legend class="field-label">{{ label }}</legend>
    <div class="chip-row">
      <button
        v-for="conference in options"
        :key="conference"
        type="button"
        class="chip-toggle"
        :class="{ 'is-on': modelValue.includes(conference) }"
        :aria-pressed="modelValue.includes(conference)"
        @click="toggle(conference)"
      >
        <span
          class="conf-dot"
          :style="{ background: conferenceColors[conference] }"
          aria-hidden="true"
        ></span>
        {{ conference }}
      </button>
    </div>
  </fieldset>
</template>

<style scoped>
.chip-field {
  margin: 0;
  padding: 0;
  border: 0;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
