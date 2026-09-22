<script setup lang="ts">
/**
 * 年份区间选择。列表页用起止两个选择框，以便完整保留从首页/趋势页带过来的年份区间
 * （阶段 1 已确认这是相对原型的必要增强）。
 * unlimited 为 true 时提供“不限”，此时值为 null，表示该端不设限制。
 */
const props = defineProps<{
  yearFrom: number | null
  yearTo: number | null
  years: readonly number[]
  label?: string
  unlimited?: boolean
}>()

const emit = defineEmits<{
  'update:yearFrom': [value: number | null]
  'update:yearTo': [value: number | null]
}>()

const UNLIMITED = ''

function toValue(raw: string): number | null {
  return raw === UNLIMITED ? null : Number(raw)
}

function onFromChange(event: Event): void {
  const value = toValue((event.target as HTMLSelectElement).value)
  emit('update:yearFrom', value)
  if (value !== null && props.yearTo !== null && value > props.yearTo) {
    emit('update:yearTo', value)
  }
}

function onToChange(event: Event): void {
  const value = toValue((event.target as HTMLSelectElement).value)
  emit('update:yearTo', value)
  if (value !== null && props.yearFrom !== null && value < props.yearFrom) {
    emit('update:yearFrom', value)
  }
}

/** select 的 value 必须是字符串，null 用空串表示 */
function selectValue(value: number | null): string {
  return value === null ? UNLIMITED : String(value)
}
</script>

<template>
  <div class="year-range">
    <span class="field-label">{{ label ?? '年份范围' }}</span>
    <div class="year-controls">
      <label class="visually-hidden" for="year-from">起始年份</label>
      <select
        id="year-from"
        class="select"
        :value="selectValue(yearFrom)"
        @change="onFromChange"
      >
        <option v-if="unlimited" :value="UNLIMITED">不限</option>
        <option v-for="year in years" :key="`from-${year}`" :value="String(year)">
          {{ year }}
        </option>
      </select>
      <span class="year-sep">至</span>
      <label class="visually-hidden" for="year-to">结束年份</label>
      <select id="year-to" class="select" :value="selectValue(yearTo)" @change="onToChange">
        <option v-if="unlimited" :value="UNLIMITED">不限</option>
        <option v-for="year in years" :key="`to-${year}`" :value="String(year)">
          {{ year }}
        </option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.year-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.year-controls .select {
  width: auto;
  min-width: 88px;
}

.year-sep {
  color: var(--color-text-faint);
  font-size: 14px;
}
</style>
