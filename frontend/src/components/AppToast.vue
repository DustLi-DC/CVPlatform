<script setup lang="ts">
import { useToast } from '../composables/useToast'

const { toasts, dismissToast } = useToast()
</script>

<template>
  <div class="toast-layer" aria-live="polite" aria-atomic="false">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="`toast-${toast.tone}`">
      <span>{{ toast.text }}</span>
      <button
        type="button"
        class="toast-close"
        aria-label="关闭提示"
        @click="dismissToast(toast.id)"
      >
        ×
      </button>
    </div>
  </div>
</template>

<style scoped>
.toast-layer {
  position: fixed;
  bottom: 32px;
  left: 50%;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  transform: translateX(-50%);
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: min(640px, 90vw);
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  background: var(--color-text-strong);
  box-shadow: var(--shadow-overlay);
  color: #fff;
  font-size: 14px;
  pointer-events: auto;
}

.toast-warning {
  background: #78350f;
}

.toast-neutral {
  background: var(--color-text-muted);
}

.toast-close {
  padding: 0 2px;
  border: 0;
  background: none;
  color: inherit;
  font-size: 16px;
  line-height: 1;
  opacity: 0.7;
  cursor: pointer;
}

.toast-close:hover {
  opacity: 1;
}
</style>
