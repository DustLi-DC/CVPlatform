<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getHealth } from '../api/health'

const loading = ref(false)
const status = ref('等待检查')

async function checkConnection() {
  loading.value = true
  status.value = '正在连接后端…'
  try {
    const result = await getHealth()
    status.value = result.status === 'ok' ? `${result.service} 已连接` : '后端响应异常'
  } catch {
    status.value = '后端未连接，请先启动 FastAPI 服务。'
  } finally {
    loading.value = false
  }
}

onMounted(checkConnection)
</script>

<template>
  <main>
    <p class="eyebrow">CVPR · ICCV · ECCV</p>
    <h1>CVPlatform</h1>
    <p>计算机视觉顶会论文分析平台</p>
    <section aria-labelledby="environment-title">
      <h2 id="environment-title">开发环境已初始化</h2>
      <p>Vue 3 + TypeScript + Vite / Python + FastAPI</p>
      <p role="status">{{ status }}</p>
      <button type="button" :disabled="loading" @click="checkConnection">
        {{ loading ? '检查中…' : '检查后端连接' }}
      </button>
    </section>
  </main>
</template>

<style scoped>
main {
  max-width: 760px;
  margin: 10vh auto;
  padding: 24px;
}

.eyebrow {
  color: #526076;
  letter-spacing: 0.08em;
}

h1 {
  margin-bottom: 12px;
  font-size: clamp(2rem, 7vw, 3rem);
}

section {
  margin-top: 32px;
  padding: 24px;
  background: white;
  border: 1px solid #dde2e9;
  border-radius: 12px;
}

h2 {
  margin-top: 0;
  font-size: 1.25rem;
}

button {
  min-height: 44px;
  padding: 10px 18px;
  border: 0;
  border-radius: 6px;
  background: #224fbb;
  color: white;
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: wait;
}
</style>
