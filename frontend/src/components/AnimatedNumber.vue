<script setup lang="ts">
/**
 * 数字滚动显示：值变化时在 duration 毫秒内从旧值补间到新值（rAF + 缓出）。
 *
 * 用途：年份推进时侧栏的「计数 / 分母 / 占比」与榜单条目数会整块变化，
 * 直接替换会让数字"闪一下"；补间后视觉上是数字在走，落点仍是接口返回的真实值。
 *
 * - `null` 表示"没有样本"，按全站约定显示为「—」而**不是 0**，也不做补间
 *   （从一个数补到 null 没有意义，直接切换）；
 * - 只在值真的变化时启动补间，首次渲染直接显示目标值；
 * - `prefers-reduced-motion: reduce` 时不做补间，直接就位；
 * - 卸载时取消未完成的 rAF，避免回调写进已销毁的组件；
 * - 等宽数字（tabular-nums）：补间过程中宽度不跳，同行文字不会左右抖动。
 */
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number | null
    /** 小数位数：占比用 2（与 formatShare 一致），计数用 0 */
    digits?: number
    /** 补间时长，毫秒 */
    duration?: number
  }>(),
  { digits: 0, duration: 420 },
)

function display(value: number | null): string {
  return value === null ? '—' : value.toFixed(props.digits)
}

const text = ref(display(props.value))
let frame: number | null = null

function cancel(): void {
  if (frame !== null) {
    cancelAnimationFrame(frame)
    frame = null
  }
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

watch(
  () => props.value,
  (next, previous) => {
    cancel()
    const tweenable =
      next !== null &&
      previous !== null &&
      previous !== undefined &&
      Number.isFinite(next) &&
      Number.isFinite(previous) &&
      next !== previous
    if (!tweenable || prefersReducedMotion()) {
      text.value = display(next)
      return
    }
    const from = previous as number
    const target = next as number
    const started = performance.now()
    const tick = (now: number): void => {
      const ratio = Math.min((now - started) / props.duration, 1)
      // 三次缓出：起步快、收尾慢，读数时更自然
      const eased = 1 - (1 - ratio) ** 3
      text.value = (from + (target - from) * eased).toFixed(props.digits)
      if (ratio < 1) {
        frame = requestAnimationFrame(tick)
      } else {
        frame = null
        // 收尾必须落在精确值上，不能停在补间的近似结果
        text.value = target.toFixed(props.digits)
      }
    }
    frame = requestAnimationFrame(tick)
  },
)

onBeforeUnmount(cancel)
</script>

<template>
  <span class="animated-number">{{ text }}</span>
</template>

<style scoped>
.animated-number {
  font-variant-numeric: tabular-nums;
}
</style>
