<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { getHealth } from '../api/health'

type ConnectionState = 'checking' | 'ok' | 'failed'

const route = useRoute()
const state = ref<ConnectionState>('checking')
const serviceName = ref('')

async function checkConnection(): Promise<void> {
  state.value = 'checking'
  try {
    const result = await getHealth()
    state.value = result.status === 'ok' ? 'ok' : 'failed'
    serviceName.value = result.service
  } catch {
    state.value = 'failed'
    serviceName.value = ''
  }
}

onMounted(checkConnection)

// 切换页面时重新检查：后端在页面停留期间恢复或中断后，指示器不会停在过期状态
watch(() => route.fullPath, checkConnection)
</script>

<template>
  <footer class="site-footer">
    <div class="layout-container footer-inner">
      <div class="footer-left">
        <span>
          CVPlatform · 课程项目 · 页面数值来自平台采集的会议论文数据，
          覆盖范围与统计口径见「关于平台」，不等同于整个领域的结论。
        </span>
      </div>
      <div class="footer-right">
        <span class="conn" role="status">
          <span class="conn-dot" :class="`is-${state}`" aria-hidden="true"></span>
          后端连接：
          <template v-if="state === 'checking'">检查中…</template>
          <template v-else-if="state === 'ok'">{{ serviceName }} 已连接</template>
          <template v-else>未连接</template>
        </span>
        <button
          type="button"
          class="link-action"
          :disabled="state === 'checking'"
          @click="checkConnection"
        >
          重新检查
        </button>
        <RouterLink class="footer-link" to="/about">统计口径说明</RouterLink>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.site-footer {
  margin-top: auto;
  padding: 24px 0;
}

.footer-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 20px;
  border-top: 1px solid var(--color-border);
  font-size: 12px;
  color: var(--color-text-subtle);
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.conn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.conn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-text-faint);
}

.conn-dot.is-ok {
  background: var(--color-ok-text);
}

.conn-dot.is-failed {
  background: var(--color-danger);
}

.footer-link:hover {
  color: var(--color-primary);
}

@media (max-width: 900px) {
  .footer-inner {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
