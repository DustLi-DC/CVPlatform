<script setup lang="ts">
/**
 * 页面 5 · 论文详情（对应原型 05_detail）。
 * 路径为 /papers/:id；原型用 detail.html?id=，此处用路径参数以便分享与刷新。
 *
 * 关键词分「来源提供的关键词」与「系统提取的关键词」两块展示：前者只作展示，
 * 参与 Top 10 / 图谱 / 趋势统计的是后者经主题归并后的结果。
 */
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import DemoNotice from '../components/DemoNotice.vue'
import KeywordTag from '../components/KeywordTag.vue'
import PaperFormModal from '../components/PaperFormModal.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { getPaper, relatedPapers } from '../demo/store'
import {
  demoConferenceYearSample,
  demoTopicCount,
  findDemoTopic,
  topicGroupColors,
} from '../demo/topics'
import { conferenceColors, type Paper } from '../types/paper'

const route = useRoute()
const router = useRouter()

const paperId = computed(() => Number(route.params.id))
const paper = computed<Paper | undefined>(() => getPaper(paperId.value))
const editOpen = ref(false)
/** 保存后用于触发重新读取（演示库为响应式，此处只需触发模板重算） */
const savedTick = ref(0)

const related = computed(() => {
  void savedTick.value
  return relatedPapers(paperId.value)
})

const sourceKeywordTags = computed(
  () => paper.value?.keywords.filter((keyword) => keyword.origin === 'author') ?? [],
)

const systemKeywordTags = computed(
  () => paper.value?.keywords.filter((keyword) => keyword.origin === 'system') ?? [],
)

const unmappedCount = computed(
  () => (paper.value?.keywords ?? []).filter((keyword) => !keyword.topic).length,
)

/** 该论文所属主题在所属会议年份的演示热度 */
const topicHeat = computed(() => {
  const target = paper.value
  if (!target) return []
  const topics = [
    ...new Set(
      target.keywords
        .filter((keyword) => keyword.origin === 'system' && keyword.topic)
        .map((keyword) => keyword.topic as string),
    ),
  ]
  const sample = demoConferenceYearSample(target.conference, target.year)
  return topics.map((topicName) => {
    const topic = findDemoTopic(topicName)
    const count = topic ? demoTopicCount(topic, target.conference, target.year) : null
    return {
      topicName,
      group: topic ? topic.group : ('none' as const),
      count,
      sample,
      share: sample && count !== null ? (count / sample) * 100 : null,
    }
  })
})

function onSaved(): void {
  savedTick.value += 1
}

/** 点击关键词标签 → 按该关键词进入论文列表（与原型详情页的跳转一致） */
function openKeyword(name: string): void {
  void router.push({ path: '/papers', query: { kw: name } })
}
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

    <div v-if="!paper" class="card detail-missing">
      <p class="missing-title">没有找到这篇论文</p>
      <p class="missing-desc">
        演示库中没有编号为 {{ route.params.id }} 的记录，可能是链接有误或该记录已被删除。
      </p>
      <RouterLink class="btn btn-primary" to="/papers">返回论文列表</RouterLink>
    </div>

    <template v-else>
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
                  :display="paper.displayStatus"
                  :keyword="
                    paper.keywordStatus === 'done' && paper.systemKeywords.length === 0
                      ? 'empty'
                      : paper.keywordStatus
                  "
                />
              </div>
              <h1 class="detail-title">{{ paper.title }}</h1>
              <p v-if="paper.codeScopeMismatch" class="code-note">{{ paper.codeNote }}</p>
            </div>
            <div class="title-actions">
              <button type="button" class="btn btn-secondary" @click="editOpen = true">
                编辑论文信息
              </button>
              <a
                v-if="paper.landingUrl"
                class="btn btn-primary"
                :href="paper.landingUrl"
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
                  该论文的关键词处理结果为{{ paper.keywordStatus === 'done' ? '空' : '未完成' }}。
                  成功但为空仍计入分析分母，此处如实显示，不用占位词填充。
                </span>
              </div>
              <p v-if="unmappedCount" class="keyword-unmapped">
                其中 {{ unmappedCount }} 个关键词尚未归并到任何主题，已标注为「未归类」。
              </p>
            </div>
          </section>

          <section class="card section-card">
            <h2 class="section-title">数据来源与获取信息</h2>
            <dl class="source-grid">
              <div>
                <dt>数据来源</dt>
                <dd>{{ paper.sources.length ? paper.sources.map((item) => item.source).join('、') : '—' }}</dd>
              </div>
              <div>
                <dt>获取时间</dt>
                <dd>{{ paper.retrievedAt ?? '—' }}</dd>
              </div>
              <div>
                <dt>原文链接</dt>
                <dd>{{ paper.landingUrl ?? '—' }}</dd>
              </div>
              <div>
                <dt>最近更新</dt>
                <dd>{{ paper.updatedAt ?? '—' }}</dd>
              </div>
            </dl>
            <div v-if="paper.sources.length" class="source-ids">
              <p v-for="item in paper.sources" :key="item.sourceId" class="source-id">
                {{ item.source }} · {{ item.sourceId }}
              </p>
            </div>
            <DemoNotice class="source-notice" tone="warn">
              本页摘要、关键词与来源信息为课程演示数据，仅用于界面核对；真实数据接入后，此处将显示实际来源与获取时间。
            </DemoNotice>
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
                <dd>{{ paper.displayStatus }}</dd>
              </div>
              <div>
                <dt>关键词状态</dt>
                <dd>{{ paper.keywordStatus === 'done' && !paper.systemKeywords.length ? '已处理·空' : paper.keywordStatus }}</dd>
              </div>
            </dl>
          </section>

          <section class="card side-card">
            <h2 class="side-title">该论文所属方向热度</h2>
            <div v-if="topicHeat.length" class="heat-list">
              <div v-for="item in topicHeat" :key="item.topicName" class="heat-item">
                <div class="heat-head">
                  <span class="heat-topic">
                    <span
                      class="legend-dot"
                      :style="{ background: topicGroupColors[item.group] }"
                      aria-hidden="true"
                    ></span>
                    {{ item.topicName }}
                  </span>
                  <span class="heat-share">
                    {{ item.share === null ? '无可用数据' : `${item.share.toFixed(2)}%` }}
                  </span>
                </div>
                <p class="heat-meta">
                  <template v-if="item.sample === null">
                    {{ paper.conference }} {{ paper.year }} 年没有纳入分析的样本
                  </template>
                  <template v-else>
                    {{ item.count }} / {{ item.sample.toLocaleString('zh-CN') }} 篇（{{ paper.conference }} {{ paper.year }}）
                  </template>
                </p>
              </div>
            </div>
            <p v-else class="side-empty">该论文暂无已归并到主题的系统关键词。</p>
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
                :to="`/papers/${item.id}`"
              >
                <span class="line-2 related-title">{{ item.title }}</span>
                <span class="related-meta">{{ item.conference }} {{ item.year }} · {{ item.code }}</span>
              </RouterLink>
              <p v-if="!related.length" class="side-empty">
                暂无同主题论文；可在论文管理中补充采集。
              </p>
            </div>
            <RouterLink class="side-more" to="/papers">在论文管理中查看更多</RouterLink>
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
