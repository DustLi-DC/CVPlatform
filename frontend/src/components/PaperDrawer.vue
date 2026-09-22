<script setup lang="ts">
/**
 * 关键词相关论文抽屉（原型首页右侧 440px 抽屉）。
 * 展示当前范围内的相关论文数、占比、共现最强主题与示例论文，并携带筛选条件进入列表。
 *
 * 数据来源：首页在阶段 8 接入统计接口前使用演示数据，因此这里只约定渲染所需的最小字段，
 * 不绑定论文接口的完整类型；阶段 8 换成 `GET /api/stats/keyword/{name}/papers` 时无需改动本组件。
 */
import { onBeforeUnmount, watch } from 'vue'
import { RouterLink } from 'vue-router'

/** 抽屉渲染示例论文所需的最小字段，论文列表项与演示数据都满足该结构 */
export interface DrawerPaperRef {
  id: number
  code: string
  title: string
  conference: string
  year: number
}

const props = defineProps<{
  open: boolean
  topicName: string
  /** 当前范围内该主题的论文数 */
  count: number
  /** 占样本比例（热度），分母为 0 时传 null */
  share: number | null
  /** 共现最强的主题（最多 4 个） */
  coTopics: { name: string; weight: number }[]
  papers: DrawerPaperRef[]
  /** 进入论文列表时保留的筛选条件 */
  listQuery: Record<string, string>
}>()

const emit = defineEmits<{
  close: []
}>()

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      document.body.style.overflow = 'hidden'
      window.addEventListener('keydown', onKeydown)
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

function shareText(): string {
  return props.share === null ? '—' : `${props.share.toFixed(2)}%`
}
</script>

<template>
  <div v-if="open" class="drawer-layer">
    <div class="drawer-backdrop" @click="emit('close')"></div>
    <aside class="drawer-panel" role="dialog" aria-modal="true" aria-label="关键词相关论文">
      <header class="drawer-header">
        <div>
          <p class="drawer-eyebrow">关键词相关论文（演示数据）</p>
          <h3 class="drawer-title">{{ topicName }}</h3>
        </div>
        <button
          type="button"
          class="modal-close"
          aria-label="关闭抽屉"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <div class="drawer-body">
        <div class="drawer-stats">
          <div class="drawer-stat">
            <div class="drawer-stat-label">当前范围相关论文</div>
            <div class="drawer-stat-value">{{ count }} 篇</div>
          </div>
          <div class="drawer-stat">
            <div class="drawer-stat-label">占样本比例（热度）</div>
            <div class="drawer-stat-value">{{ shareText() }}</div>
          </div>
        </div>

        <section class="drawer-section">
          <h4 class="drawer-section-title">共现最强的关键词</h4>
          <div class="drawer-co">
            <template v-if="coTopics.length">
              <span v-for="item in coTopics" :key="item.name" class="tag">
                {{ item.name }} <span class="co-weight">· {{ item.weight }} 次</span>
              </span>
            </template>
            <span v-else class="drawer-empty">暂无共现记录</span>
          </div>
        </section>

        <section class="drawer-section">
          <div class="drawer-section-head">
            <h4 class="drawer-section-title">示例论文</h4>
            <span class="drawer-hint">点击标题查看详情</span>
          </div>
          <div class="drawer-papers">
            <RouterLink
              v-for="paper in papers"
              :key="paper.id"
              class="drawer-paper"
              :to="`/papers/${paper.id}`"
            >
              <span class="line-2 drawer-paper-title">{{ paper.title }}</span>
              <span class="drawer-paper-meta">
                {{ paper.conference }} {{ paper.year }} · {{ paper.code }}
              </span>
            </RouterLink>
            <p v-if="!papers.length" class="drawer-empty">
              该方向暂无示例论文，可在论文管理中补充采集。
            </p>
          </div>
        </section>
      </div>

      <footer class="drawer-footer">
        <RouterLink class="btn btn-primary btn-block" :to="{ path: '/papers', query: listQuery }">
          查看全部相关论文
        </RouterLink>
        <p class="drawer-footer-hint">跳转时会保留当前会议、年份与关键词条件</p>
      </footer>
    </aside>
  </div>
</template>

<style scoped>
.drawer-layer {
  position: fixed;
  inset: 0;
  z-index: 40;
}

.drawer-backdrop {
  position: absolute;
  inset: 0;
  background: rgb(15 23 42 / 30%);
}

.drawer-panel {
  position: absolute;
  top: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  width: 440px;
  max-width: 100%;
  height: 100%;
  background: var(--color-surface);
  box-shadow: var(--shadow-overlay);
}

.drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border);
}

.drawer-eyebrow {
  font-size: 11px;
  color: var(--color-text-subtle);
}

.drawer-title {
  margin-top: 4px;
  font-size: 18px;
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

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.drawer-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.drawer-stat {
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.drawer-stat-label {
  font-size: 11px;
  color: var(--color-text-subtle);
}

.drawer-stat-value {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text-strong);
}

.drawer-section {
  margin-bottom: 20px;
}

.drawer-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.drawer-section-title {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.drawer-section-head .drawer-section-title {
  margin-bottom: 0;
}

.drawer-hint {
  font-size: 11px;
  color: var(--color-text-faint);
}

.drawer-co {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.co-weight {
  color: var(--color-text-faint);
}

.drawer-papers {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}

.drawer-paper {
  display: block;
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.drawer-paper:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-pop);
}

.drawer-paper-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}

.drawer-paper-meta {
  display: block;
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-text-subtle);
}

.drawer-empty {
  font-size: 12px;
  color: var(--color-text-faint);
}

.drawer-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--color-border);
}

.drawer-footer-hint {
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-text-subtle);
  text-align: center;
}

@media (max-width: 520px) {
  .drawer-panel {
    width: 100%;
  }
}
</style>
