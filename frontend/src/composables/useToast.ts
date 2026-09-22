/**
 * 轻提示（Toast）：全局单例队列，供各页面提交后反馈使用。
 * 组件卸载不影响队列，由布局中的 AppToast 统一渲染。
 */
import { readonly, ref } from 'vue'

export type ToastTone = 'success' | 'neutral' | 'warning'

export interface ToastMessage {
  id: number
  text: string
  tone: ToastTone
}

const toasts = ref<ToastMessage[]>([])
const TOAST_DURATION_MS = 3200
let nextId = 1

export function pushToast(text: string, tone: ToastTone = 'success'): void {
  const id = nextId
  nextId += 1
  toasts.value = [...toasts.value, { id, text, tone }]
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }, TOAST_DURATION_MS)
}

export function dismissToast(id: number): void {
  toasts.value = toasts.value.filter((toast) => toast.id !== id)
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    pushToast,
    dismissToast,
  }
}
