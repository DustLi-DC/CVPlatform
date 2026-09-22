<script setup lang="ts">
/**
 * 页面 5 · 论文详情（对应原型 05_detail）。
 * 路径为 /papers/:id；原型用 detail.html?id=，此处用路径参数以便分享与刷新。
 *
 * 已接入阶段 3 的真实接口：详情、同主题论文、编辑保存。
 * 关键词分「来源提供的关键词」与「系统提取的关键词」两块展示：前者只作展示，
 * 参与 Top 10 / 图谱 / 趋势统计的是后者经主题归并后的结果。
 * 「所属方向热度」依赖统计接口（阶段 8），此处只呈现接入位置，不用演示数值填充。
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  ApiError,
  fetchPaper,
  fetchRelatedPapers,
} from '../api/paperApi'
import DemoNotice from '../components/DemoNotice.vue'
import KeywordTag from '../components/KeywordTag.vue'
import PaperFormModal from '../components/PaperFormModal.vue'
import StatusBadge from '../components/StatusBadge.vue'
import {
  conferenceColors,
  keywordBadgeFor,
  type PaperDetail,
  type PaperListItem,
} from '../types/paper'

const route = useRoute()
const router = useRouter()

const paperId = computed(() => Number(route.params.id))

const paper = ref<PaperDetail | null>(null)
const related = ref<PaperListItem[]>([])
const loading = ref(false)
const loadError = ref('')
const notFound = ref(false)
const editOpen = ref(false)

const sourceKeywordTags = computed(
  () => paper.value?.keywords.filter((keyword) => keyword.origin === 'author') ?? [],
)

const systemKeywordTags = computed(
  () => paper.value?.keywords.filter((keyword) => keyword.origin === 'system') ?? [],
)

const unmappedCount = computed(
  () => (paper.value?.keywords ?? []).filter((keyword) => !keyword.topic).length,
)

/** 数据来源标识的名称汇总，用于详情页「数据来源」一行 */
const sourceNames = computed(() => {
  const sources = paper.value?.sources ?? []
  return sources.length ? sources.map((item) => item.source).join('、') : '—'
})

/** 该系统关键词已归并到主题的数量，用于说明统计口径的适用范围 */
const mappedSystemCount = computed(
  () =>
    (paper.value?.keywords ?? []).filter(
      (keyword) => keyword.origin === 'system' && keyword.topic,
    ).length,
)

async function load(): Promise<void> {
  if (!Number.isFinite(paperId.value) || paperId.value <= 0) {
    notFound.value = true
    return
  }
  loading.value = true
  loadError.value = ''
  notFound.value = false
  try {
    const detail = await fetchPaper(paperId.value)
    paper.value = detail
    // 同主题论文失败不影响主体内容展示
    try {
      related.value = await fetchRelatedPapers(paperId.value)
    } catch {
      related.value = []
    }
  } catch (error) {
    paper.value = null
    related.value = []
    if (error instanceof ApiError && error.code === 'paper_not_found') {
      notFound.value = true
    } else {
      loadError.value =
        error instanceof ApiError ? error.message : '读取论文详情失败，请稍后重试。'
    }
  } finally {
    loading.value = false
  }
}

async function onSaved(): Promise<void> {
  await load()
}

/** 点击关键词标签 → 按该关键词进入论文列表（与原型详情页的跳转一致） */
function openKeyword(name: string): void {
  void router.push({ path: '/papers', query: { kw: name } })
}

// 详情之间跳转（相关论文）时重新加载
watch(paperId, () => void load(), { immediate: true })
</script>

<template>
  <div>
    <nav class="breadcrumb" aria-label="面包屑">
      <RouterLink class="btn btn-secondary btn-sm" :to="{ path: '/papers', query: route.query }">
        ← 返回论文列表
      </RouterLink>
      <span class="crumb-sep">/</span>
      <RouterLink class="crumb-link" to="/papers">论文管理</RouterLink>
      <span class="crumb-sep">/</span>
      <span class="crumb-current">论文详情</span>
    </nav>

    <div v-if="loading" class="card detail-missing" role="status">
      <p class="missing-title">正在加载论文详情…</p>
    </div>

    <div v-else-if="loadError" class="card detail-missing" role="alert">
      <p class="missing-title">论文详情加载失败</p>
      <p class="missing-desc">{{ loadError }}</p>
      <div class="missing-actions">
        <button type="button" class="btn btn-primary" @click="load">重试</button>
        <RouterLink class="btn btn-secondary" :to="{ path: '/papers', query: route.query }">
          返回论文列表
        </RouterLink>
      </div>
    </div>

    <div v-else-if="notFound" class="card detail-missing">
      <p class="missing-title">没有找到这篇论文</p>
      <p class="missing-desc">
        论文库中没有编号为 {{ route.params.id }} 的记录，可能是链接有误或该记录已被删除。
      </p>
      <RouterLink class="btn btn-primary" to="/papers">返回论文列表</RouterLink>
    </div>

    <template v-else-if="paper">
      <div class="detail-grid">
        <div class="detail-main">
          <section class="card title-card">
            <div class="title-main">
              <div class="title-badges">
                <span class="badge badge-primary">
                  <span
                    class="conf-dot"
                    :style="{ background: conferenceColors[paper.conference] }"
                    aria-hidden="true"
                  ></span>
                  {{ paper.conference }} {{ paper.year }}
                </span>
                <span class="badge badge-neutral code-badge">{{ paper.code }}</span>
                <StatusBadge
                  :display="paper.display_status"
                  :keyword="keywordBadgeFor(paper)"
                />
              </div>
              <h1 class="detail-title">{{ paper.title }}</h1>
              <p v-if="paper.code_scope_mismatch" class="code-note">{{ paper.code_note }}</p>
            </div>
            <div class="title-actions">
              <button type="button" class="btn btn-secondary" @click="editOpen = true">
                编辑论文信息
              </button>
              <a
                v-if="paper.landing_url"
                class="btn btn-primary"
                :href="paper.landing_url"
                target="_blank"
                rel="noreferrer noopener"
              >
                阅读原文
              </a>
              <span v-else class="btn btn-secondary is-disabled" aria-disabled="true">
                原文链接缺失
              </span>
            </div>
          </section>

          <section class="card section-card">
            <h2 class="section-title">摘要</h2>
            <p v-if="paper.abstract" class="abstract-text">{{ paper.abstract }}</p>
            <DemoNotice v-else tone="warn" title="这篇论文的摘要缺失">
              关键词仅基于标题生成并已标注来源；补充采集成功后会回填摘要，届时将按标题与摘要重新处理关键词。
            </DemoNotice>
          </section>

          <section class="card section-card">
            <div class="section-head">
              <h2 class="section-title">关键词</h2>
              <span class="section-hint">点击关键词可查看该方向的论文与热度走势</span>
            </div>

            <div class="keyword-block">
              <h3 class="keyword-title">
                来源提供的关键词
                <span class="keyword-note">（会议论文页或数据集自带，只作展示）</span>
              </h3>
              <div class="keyword-row">
                <template v-if="sourceKeywordTags.length">
                  <KeywordTag
                    v-for="keyword in sourceKeywordTags"
                    :key="`author-${keyword.name}`"
                    :name="keyword.name"
                    origin="author"
                    :topic="keyword.topic"
                    @click="openKeyword(keyword.name)"
                  />
                </template>
                <span v-else class="keyword-empty">该论文没有来源提供的作者关键词</span>
              </div>
            </div>

            <div class="keyword-block is-separated">
              <h3 class="keyword-title">
                系统提取的关键词
                <span class="keyword-note">（停用词过滤 + TF-IDF 与 TextRank，经主题归并后用于统计）</span>
              </h3>
              <div class="keyword-row">
                <template v-if="systemKeywordTags.length">
                  <KeywordTag
                    v-for="keyword in systemKeywordTags"
                    :key="`system-${keyword.name}`"
                    :name="keyword.name"
                    origin="system"
                    :topic="keyword.topic"
                    @click="openKeyword(keyword.name)"
                  />
                </template>
                <span v-else class="keyword-empty">
                  该论文的关键词处理结果为{{ paper.keyword_status === 'done' ? '空' : '未完成' }}。
                  成功但为空仍计入分析分母，此处如实显示，不用占位词填充。
                </span>
              </div>
              <p v-if="unmappedCount" class="keyword-unmapped">
                其中 {{ unmappedCount }} 个关键词尚未归并到任何主题，已标注为「未归类」；
                主题归并表在阶段 6 由真实高频词产出后回填。
              </p>
              <p v-else-if="mappedSystemCount" class="keyword-unmapped">
                已归并到 {{ mappedSystemCount }} 个主题，参与统计的是这些归并后的主题。
              </p>
            </div>
          </section>

          <section class="card section-card">
            <h2 class="section-title">数据来源与获取信息</h2>
            <dl class="source-grid">
              <div>
                <dt>数据来源</dt>
                <dd>{{ sourceNames }}</dd>
              </div>
              <div>
                <dt>获取时间</dt>
                <dd>{{ paper.retrieved_at ?? '—' }}</dd>
              </div>
              <div>
                <dt>原文链接</dt>
                <dd>
                  <a
                    v-if="paper.landing_url"
                    class="source-link"
                    :href="paper.landing_url"
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {{ paper.landing_url }}
                  </a>
                  <span v-else class="source-missing">缺失</span>
                </dd>
              </div>
              <div>
                <dt>最近更新</dt>
                <dd>{{ paper.updated_at ?? '—' }}</dd>
              </div>
            </dl>
            <div v-if="paper.sources.length" class="source-ids">
              <p
                v-for="item in paper.sources"
                :key="`${item.source}-${item.source_id}`"
                class="source-id"
              >
                {{ item.source }} · {{ item.source_id }}
              </p>
            </div>
            <p v-else class="source-missing">
              暂无可追溯的来源标识：该记录为手工录入，尚未通过采集接口写入来源信息。
            </p>
            <p v-if="!paper.landing_url" class="source-missing">
              原文链接缺失时不影响关键词与统计，但无法从本页直接打开会议论文页。
            </p>
          </section>
        </div>

        <aside class="detail-side">
          <section class="card side-card">
            <h2 class="side-title">基本信息</h2>
            <dl class="side-list">
              <div>
                <dt>会议</dt>
                <dd>{{ paper.conference }}</dd>
              </div>
              <div>
                <dt>年份</dt>
                <dd>{{ paper.year }}</dd>
              </div>
              <div>
                <dt>论文编号</dt>
                <dd class="mono">{{ paper.code }}</dd>
              </div>
              <div>
                <dt>数据状态</dt>
                <dd>{{ paper.display_status }}</dd>
              </div>
              <div>
                <dt>关键词状态</dt>
                <dd>{{ keywordBadgeFor(paper) === 'empty' ? '已处理·空' : paper.keyword_status }}</dd>
              </div>
            </dl>
          </section>

          <section class="card side-card">
            <h2 class="side-title">该论文所属方向热度</h2>
            <p class="side-empty">
              所属方向热度需要统计接口，将在阶段 8 接入；本阶段不显示演示数值。
            </p>
            <p v-if="mappedSystemCount" class="side-hint">
              该论文已有 {{ mappedSystemCount }} 个系统关键词归并到主题，届时可直接查看对应方向的热度与走势。
            </p>
            <RouterLink class="btn btn-secondary btn-block side-action" to="/trends">
              查看热度走势对比
            </RouterLink>
          </section>

          <section class="card side-card">
            <h2 class="side-title">相关论文 / 同主题论文</h2>
            <div class="related-list">
              <RouterLink
                v-for="item in related"
                :key="item.id"
                class="related-item"
                :to="{ name: 'paper-detail', params: { id: item.id }, query: route.query }"
              >
                <span class="line-2 related-title">{{ item.title }}</span>
                <span class="related-meta">
                  {{ item.conference }} {{ item.year }} · {{ item.code }}
                </span>
              </RouterLink>
              <p v-if="!related.length" class="side-empty">
                暂无同主题论文。同主题关系依据系统关键词归并后的主题，主题表在阶段 6 回填；
                在此之前为空属正常，可用「采集与导入」补充论文。
              </p>
            </div>
            <RouterLink class="side-more" :to="{ path: '/papers', query: route.query }">
              在论文管理中查看更多
            </RouterLink>
          </section>
        </aside>
      </div>

      <div class="detail-foot">
        <RouterLink class="btn btn-secondary" :to="{ path: '/papers', query: route.query }">
          ← 返回论文列表
        </RouterLink>
        <div class="foot-actions">
          <RouterLink class="btn btn-secondary" to="/trends">对比研究趋势</RouterLink>
          <RouterLink class="btn btn-primary" to="/collect">补充采集论文</RouterLink>
        </div>
      </div>

      <PaperFormModal
        :open="editOpen"
        :paper="paper"
        @close="editOpen = false"
        @saved="onSaved"
      />
    </template>
  </div>
</template>

<style scoped>
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.crumb-sep {
  color: var(--color-text-faint);
}

.crumb-link:hover {
  color: var(--color-text-strong);
}

.crumb-current {
  color: var(--color-text-muted);
}

.detail-missing {
  padding: 48px 24px;
  text-align: center;
}

.missing-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.missing-desc {
  margin: 8px 0 20px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.missing-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}

.source-link {
  color: var(--color-primary);
  word-break: break-all;
}

.source-link:hover {
  text-decoration: underline;
}

.source-missing {
  font-size: 12px;
  color: var(--color-text-faint);
}

.side-hint {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-subtle);
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 8fr) minmax(0, 4fr);
  gap: 24px;
  align-items: start;
}

.detail-main,
.detail-side {
  display: grid;
  gap: 20px;
}

.title-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 28px;
}

.title-main {
  min-width: 0;
}

.title-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.code-badge {
  font-family: var(--font-mono);
}

.detail-title {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.5;
  color: var(--color-text-strong);
}

.code-note {
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-warn-text);
}

.title-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 0 0 auto;
}

.btn.is-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.section-card {
  padding: 24px 28px;
}

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.section-title {
  margin-bottom: 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.section-head .section-title {
  margin-bottom: 0;
}

.section-hint {
  font-size: 12px;
  color: var(--color-text-subtle);
}

.abstract-text {
  font-size: 14px;
  line-height: 1.85;
  color: var(--color-text-muted);
}

.keyword-block.is-separated {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--color-border-soft);
}

.keyword-title {
  margin-bottom: 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.keyword-note {
  font-weight: 400;
  color: var(--color-text-faint);
}

.keyword-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.keyword-empty {
  font-size: 12px;
  color: var(--color-text-faint);
}

.keyword-unmapped {
  margin-top: 10px;
  font-size: 11px;
  color: var(--color-text-faint);
}

.source-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 40px;
}

.source-grid > div {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  font-size: 14px;
}

.source-grid dt {
  flex: 0 0 auto;
  color: var(--color-text-subtle);
}

.source-grid dd {
  text-align: right;
  color: var(--color-text);
  word-break: break-all;
}

.source-ids {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-soft);
}

.source-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text-faint);
  word-break: break-all;
}

.source-notice {
  margin-top: 16px;
}

.side-card {
  padding: 20px 24px;
}

.side-title {
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.side-list {
  display: grid;
  gap: 10px;
}

.side-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 14px;
}

.side-list dt {
  color: var(--color-text-subtle);
}

.side-list dd {
  color: var(--color-text);
}

.side-list dd.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}

.heat-list {
  display: grid;
  gap: 10px;
}

.heat-item {
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.heat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 14px;
}

.heat-topic {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text);
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.heat-share {
  font-weight: 600;
  color: var(--color-text-strong);
}

.heat-meta {
  margin-top: 6px;
  font-size: 11px;
  color: var(--color-text-subtle);
}

.side-empty {
  font-size: 12px;
  color: var(--color-text-faint);
}

.side-action {
  margin-top: 16px;
}

.related-list {
  display: grid;
  gap: 10px;
}

.related-item {
  display: block;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.related-item:hover {
  border-color: var(--color-primary);
}

.related-title {
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-text);
}

.related-meta {
  display: block;
  margin-top: 6px;
  font-size: 11px;
  color: var(--color-text-subtle);
}

.side-more {
  display: block;
  margin-top: 12px;
  font-size: 12px;
  color: var(--color-primary);
  text-align: center;
}

.detail-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 24px;
  padding: 16px 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.foot-actions {
  display: flex;
  gap: 12px;
}

/* 窄窗口：主体与侧栏改单列 */
@media (max-width: 1200px) {
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .title-card {
    flex-direction: column;
  }

  .title-actions {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .source-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .source-grid > div {
    flex-direction: column;
  }

  .source-grid dd {
    text-align: left;
  }

  .detail-foot {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
