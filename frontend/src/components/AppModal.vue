<script setup lang="ts">
/**
 * 基础弹窗：遮罩点击与 Esc 关闭，打开时锁定滚动并把焦点移入弹窗。
 * 原型一致性：容器默认隐藏，仅在打开时渲染；关闭后清理事件监听。
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    /** 弹窗宽度，原型为 620px（表单）与 460px（确认） */
    width?: string
    closeOnBackdrop?: boolean
  }>(),
  { width: '620px', closeOnBackdrop: true },
)

const emit = defineEmits<{
  close: []
}>()

const panel = ref<HTMLElement | null>(null)

function requestClose(): void {
  emit('close')
}

function onBackdropClick(): void {
  if (props.closeOnBackdrop) requestClose()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') requestClose()
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      document.body.style.overflow = 'hidden'
      window.addEventListener('keydown', onKeydown)
      await nextTick()
      panel.value?.focus()
      return
    }
    document.body.style.overflow = ''
    window.removeEventListener('keydown', onKeydown)
  },
)

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div v-if="open" class="modal-layer">
    <div class="modal-backdrop" @click="onBackdropClick"></div>
    <div
      ref="panel"
      class="modal-panel"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      tabindex="-1"
      :style="{ width }"
    >
      <div class="modal-header">
        <h3 class="modal-title">{{ title }}</h3>
        <button type="button" class="modal-close" aria-label="关闭弹窗" @click="requestClose">
          ×
        </button>
      </div>
      <div class="modal-body">
        <slot />
      </div>
      <div v-if="$slots.footer" class="modal-footer">
        <slot name="footer" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-layer {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.modal-backdrop {
  position: absolute;
  inset: 0;
  background: rgb(15 23 42 / 40%);
}

.modal-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  max-width: 100%;
  max-height: calc(100vh - 48px);
  border-radius: var(--radius-xl);
  background: var(--color-surface);
  box-shadow: var(--shadow-overlay);
}

.modal-panel:focus {
  outline: none;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border);
}

.modal-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.modal-close {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text-subtle);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.modal-close:hover {
  background: var(--color-neutral-bg);
}

.modal-body {
  overflow-y: auto;
  padding: 20px 24px;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border);
}
</style>
