<script setup lang="ts">
/**
 * 页面 6 · 关于平台（对应原型 06_about）。
 * 说明数据来源、覆盖范围、关键词方法、统计口径与图谱读法。
 * 数据来源一节按阶段 1 的实测结论书写：实际可用的来源是 CVF Open Access 与 ECVA，
 * 在线兜底为 OpenAlex；DBLP 实测不可用，因此不在此声明使用 DBLP。
 */
import ChartContainer from '../components/ChartContainer.vue'
import DemoNotice from '../components/DemoNotice.vue'
import PageHeader from '../components/PageHeader.vue'
import { demoCoverage, demoYears } from '../demo/coverage'
import { topicGroupColors, topicGroupLabels } from '../demo/topics'
import { conferenceColors, type Conference } from '../types/paper'

const conferenceYears = [...new Set(demoCoverage.map((item) => item.year))].sort()

function barHeight(year: number): string {
  const max = Math.max(...demoCoverage.map((item) => item.papers), 1)
  const yearsOfYear = demoCoverage.filter((item) => item.year === year)
  const total = yearsOfYear.reduce((sum, item) => sum + item.papers, 0)
  return `${Math.max(6, Math.round((total / max) * 100))}%`
}

function sampleOf(conference: string, year: number): number | null {
  const found = demoCoverage.find(
    (item) => item.conference === conference && item.year === year,
  )
  return found ? found.papers : null
}

const conferenceMeta: {
  name: Conference
  cadence: string
  intro: string
  years: string
}[] = [
  {
    name: 'CVPR',
    cadence: '每年举办',
    intro:
      'IEEE/CVF Conference on Computer Vision and Pattern Recognition，计算机视觉领域规模最大的年度会议之一，投稿与录用数量长期居前，方向覆盖检测、分割、生成、多模态等。',
    years: '2022 / 2023 / 2024 / 2025',
  },
  {
    name: 'ICCV',
    cadence: '奇数年举办',
    intro:
      'IEEE/CVF International Conference on Computer Vision，两年一次的旗舰会议之一，通常在奇数年举办，论文平均篇幅较长，方法类与理论类工作比例相对更高。',
    years: '仅奇数年有数据',
  },
  {
    name: 'ECCV',
    cadence: '偶数年举办',
    intro:
      'European Conference on Computer Vision，两年一次的欧洲旗舰会议，通常在偶数年举办，在三维视觉、几何与重建类方向上的论文占比在演示数据中较为突出。',
    years: '仅偶数年有数据',
  },
]

const keywordSteps = [
  {
    step: '1',
    title: '停用词过滤',
    desc: '先去掉 the、of、for、a 等英语功能词与「a novel」「in this paper」这类学术套话，剩下的词才有统计意义。',
  },
  {
    step: '2',
    title: 'TF-IDF 找「这个方向的专属词」',
    desc: '一个词在本篇很常见、但在整个论文集合里不常见，它会得到更高的分数。例如「三维高斯泼溅」在 2024 年之后的论文里频繁出现，就会被识别为新兴热词。',
  },
  {
    step: '3',
    title: 'TextRank 找「中心词」',
    desc: '把词与词看作一张网络，互相引用的重要词得分更高，因此「视觉语言模型」这类连接很多方向的关键词会排到前面。',
  },
  {
    step: '4',
    title: '归并与人工校对',
    desc: '同义表达（如 object detection / object detector）会归并到同一个主题；论文自带的关键词作为「来源提供的关键词」单独保留，不与系统提取结果混在一起。',
  },
]

const dataSources = [
  {
    name: 'CVF Open Access',
    scope: 'CVPR、ICCV 的论文题目、作者、摘要与原文链接',
    desc: '会议官方开放获取页面。论文题目与作者取自会议索引页，摘要取自逐篇详情页。',
  },
  {
    name: 'ECVA 会议论文页',
    scope: 'ECCV 的论文题目、作者、摘要与原文链接',
    desc: 'ECCV 官方论文入口，按年份汇总。CVF 不收录 ECCV，因此 ECCV 的样本只能来自 ECVA。',
  },
  {
    name: 'OpenAlex',
    scope: '在线兜底检索与文献元数据交叉核对',
    desc: '本地论文库未命中时按题目检索公开文献元数据，返回候选后由使用者确认，避免静默匹配错误论文。',
  },
]
</script>

<template>
  <div>
    <PageHeader
      eyebrow="页面 6 / 关于平台"
      title="关于 CVPlatform"
      description="这一页解释平台为什么这样统计。如果榜单和曲线里的数字让你有点不确定，先看这里：数据从哪来、关键词怎么抽出来、热度怎么算，以及为什么这里的结果只能当作一个观察样本。"
    />

    <section class="card about-section">
      <h2 class="section-title">平台用途与适用人群</h2>
      <p class="section-text">
        CVPlatform 把 CVPR、ICCV、ECCV 三个会议的论文题目与摘要集中起来，用关键词统计的方式告诉你：近几年哪些方向在被反复研究、
        哪些方向正在升温、哪些方向趋于平稳。核心流程是「发现热门方向 → 查看相关论文 → 阅读论文详情 → 补充采集数据 → 对比研究趋势」。
      </p>
      <div class="audience-grid">
        <div class="audience-card">
          <h3 class="audience-title">刚接触计算机视觉的同学</h3>
          <p class="audience-desc">不熟悉领域脉络时，先用榜单和图谱建立整体印象，再挑 2—3 篇代表性论文精读。</p>
        </div>
        <div class="audience-card">
          <h3 class="audience-title">想快速了解研究热点的学习者</h3>
          <p class="audience-desc">用热度走势对比某方向在三个会议的占比变化，辅助判断选题与阅读优先级。</p>
        </div>
      </div>
      <DemoNotice class="about-notice" tone="warn">
        本页面当前展示的论文条目、榜单数值与曲线均标注为演示数据，用于展示统计流程与交互方式，
        不构成对研究现状的结论。真实数据接入后，此处将替换为实际采集结果与覆盖范围。
      </DemoNotice>
    </section>

    <section class="card about-section">
      <h2 class="section-title">数据覆盖范围</h2>
      <dl class="coverage-grid">
        <div>
          <dt>会议范围</dt>
          <dd>CVPR / ICCV / ECCV</dd>
        </div>
        <div>
          <dt>年份范围</dt>
          <dd>{{ demoYears[0] }} — {{ demoYears[demoYears.length - 1] }}</dd>
        </div>
        <div>
          <dt>会议年份组合</dt>
          <dd>{{ demoCoverage.length }} 个（ICCV 奇数年 / ECCV 偶数年）</dd>
        </div>
        <div>
          <dt>论文样本量</dt>
          <dd>18,149 篇（演示）</dd>
        </div>
      </dl>

      <ChartContainer
        class="coverage-chart"
        title="各会议年份纳入分析的论文数"
        subtitle="柱高表示该会议该年份纳入分析的论文数；灰色缺口表示该年份该会议没有数据，不做零值填充。"
        unit="单位：篇"
        height="220px"
        pending-note="本图在阶段 8 接入真实覆盖数据后由 ECharts 渲染；当前先用结构相同的 DOM 柱形示意配色与缺口画法。"
      >
        <div class="mini-bars">
          <div v-for="year in conferenceYears" :key="year" class="mini-bar-col">
            <div class="mini-bar-track">
              <div class="mini-bar" :style="{ height: barHeight(year) }"></div>
            </div>
            <span class="mini-bar-label">{{ year }}</span>
            <ul class="mini-bar-legend">
              <li v-for="meta in conferenceMeta" :key="`${year}-${meta.name}`">
                <span
                  class="conf-dot"
                  :style="{ background: conferenceColors[meta.name] }"
                  aria-hidden="true"
                ></span>
                <template v-if="sampleOf(meta.name, year) === null">无数据</template>
                <template v-else>{{ sampleOf(meta.name, year) }}</template>
              </li>
            </ul>
          </div>
        </div>
      </ChartContainer>
    </section>

    <section class="card about-section">
      <h2 class="section-title">三个会议的背景</h2>
      <div class="conference-grid">
        <div v-for="meta in conferenceMeta" :key="meta.name" class="conference-card">
          <div class="conference-head">
            <span class="conference-name">
              <span
                class="conf-dot"
                :style="{ background: conferenceColors[meta.name] }"
                aria-hidden="true"
              ></span>
              {{ meta.name }}
            </span>
            <span class="tag">{{ meta.cadence }}</span>
          </div>
          <p class="conference-intro">{{ meta.intro }}</p>
          <p class="conference-years">年份规律：{{ meta.years }}</p>
        </div>
      </div>
    </section>

    <section class="card about-section">
      <h2 class="section-title">数据从哪里来</h2>
      <ul class="source-list">
        <li v-for="item in dataSources" :key="item.name">
          <div class="source-head">
            <span class="source-name">{{ item.name }}</span>
            <span class="tag">{{ item.scope }}</span>
          </div>
          <p class="source-desc">{{ item.desc }}</p>
        </li>
      </ul>
      <p class="section-text">
        <strong>采集与更新</strong>：单篇采集按完整题目检索；批量导入支持 CSV（title、conference、year）与 TXT（每行一个题目）。
        重复条目按来源标识、会议、年份与题目归一后合并，失败条目可在结果表中重试。
      </p>
      <p class="section-text">
        <strong>样本性质</strong>：首轮采用可复现的抽样式采集，每个会议年份抽取固定规模的子集，并在界面标注样本量与覆盖范围。
        因此页面上的占比只能表述为「本平台样本中的占比」，不等于整届大会全部录用论文的比例。
      </p>
    </section>

    <section class="card about-section">
      <h2 class="section-title">关键词是怎么抽出来的</h2>
      <p class="section-text">
        一句话版本：先把题目和摘要里没有意义的词去掉，再看哪些词反复出现、并且总是和别的词一起出现。
      </p>
      <ol class="step-list">
        <li v-for="item in keywordSteps" :key="item.step" class="step-item">
          <span class="step-index">{{ item.step }}</span>
          <div>
            <h3 class="step-title">{{ item.title }}</h3>
            <p class="step-desc">{{ item.desc }}</p>
          </div>
        </li>
      </ol>
      <DemoNotice class="about-notice" tone="warn">
        统计只使用系统提取的关键词经主题归并后的结果。论文自带的作者关键词只作展示，不参与 Top 10、图谱与趋势，
        避免两种来源混在一起改变口径。
      </DemoNotice>
    </section>

    <section class="card about-section">
      <h2 class="section-title">热度怎么算</h2>
      <div class="formula">
        热度 = 某会议某年份包含该主题的论文数 ÷ 该会议该年份纳入分析的论文总数 × 100%
      </div>
      <p class="section-text">
        用比例而不是绝对篇数，是为了让会议之间的规模差异可以被比较：CVPR 的样本量明显大于 ECCV，
        如果直接比较篇数，会误以为某个方向在 CVPR 更热。跨会议、跨年份汇总时，先把计数与分母合并再相除，不平均各组百分比。
      </p>
      <div class="distinction-grid">
        <div class="distinction-card">
          <h3 class="distinction-title">没有可用数据</h3>
          <p class="distinction-desc">
            该会议当年没有纳入分析（如 ICCV 的偶数年）。趋势图中显示为灰色区间，<strong>不画成 0</strong>。
          </p>
        </div>
        <div class="distinction-card">
          <h3 class="distinction-title">有数据但出现 0 次</h3>
          <p class="distinction-desc">
            该会议当年有样本，但没有任何论文匹配该主题。趋势图中落在 0 轴，表示「当时确实还没出现」。
          </p>
        </div>
      </div>
    </section>

    <section class="card about-section">
      <h2 class="section-title">图谱和图例怎么看</h2>
      <div class="legend-grid">
        <div class="legend-card">
          <h3 class="legend-title">节点 = 一个主题</h3>
          <p class="legend-desc">节点越大，说明当前筛选范围内与它相关的论文越多。</p>
        </div>
        <div class="legend-card">
          <h3 class="legend-title">连线 = 共现关系</h3>
          <p class="legend-desc">两个主题在同一篇论文的题目或摘要里同时出现，就会连一条线；线越粗，共现论文数越多。</p>
        </div>
        <div class="legend-card">
          <h3 class="legend-title">颜色 = 方向分组</h3>
          <p class="legend-desc">仅用于辅助辨识；未归类的关键词使用中性色，不强行编入某个分组。</p>
          <ul class="group-list">
            <li v-for="(label, group) in topicGroupLabels" :key="group">
              <span
                class="legend-dot"
                :style="{ background: topicGroupColors[group] }"
                aria-hidden="true"
              ></span>
              {{ label }}
            </li>
          </ul>
        </div>
      </div>
      <p class="section-text">
        会议颜色（CVPR / ICCV / ECCV）与主题分组色是两套独立概念：前者在全站固定用于标识会议，
        后者只用于图谱与榜单的分组辨识，两者不互相替代。
      </p>
    </section>

    <section class="card about-section is-last">
      <h2 class="section-title">样本趋势不等于整个领域的完整结论</h2>
      <p class="section-text">
        这里看到的一切都来自一个有限样本：三个会议、有限年份、以题目与摘要为主的文本字段。会议录用结构本身在变化，
        关键词抽取也会漏掉用不同措辞表达的同类工作，因此某个方向在某条曲线上的升降，只能说明「在这个样本里它出现得多或少了」，
        不能直接推导出整个计算机视觉领域的研究结论。如果要据此选择研究方向，建议把这里当作线索的起点：
        挑出 2—3 个方向，再去读会议论文原文与综述做交叉验证。
      </p>
    </section>
  </div>
</template>

<style scoped>
.about-section {
  margin-bottom: 20px;
  padding: 24px 28px;
}

.about-section.is-last {
  margin-bottom: 0;
}

.section-title {
  margin-bottom: 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.section-text {
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.85;
  color: var(--color-text-muted);
}

.audience-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.audience-card {
  padding: 16px 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.audience-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.audience-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-subtle);
}

.about-notice {
  margin-top: 16px;
}

.coverage-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.coverage-grid > div {
  padding: 14px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}

.coverage-grid dt {
  font-size: 11px;
  color: var(--color-text-subtle);
}

.coverage-grid dd {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.coverage-chart {
  margin-top: 20px;
}

.mini-bars {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  gap: 16px;
  height: 100%;
  padding: 20px 24px 12px;
}

.mini-bar-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  flex: 1;
  height: 100%;
  min-width: 0;
}

.mini-bar-track {
  display: flex;
  align-items: flex-end;
  width: 100%;
  max-width: 64px;
  flex: 1;
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}

.mini-bar {
  width: 100%;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
}

.mini-bar-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.mini-bar-legend {
  display: grid;
  gap: 2px;
  font-size: 10px;
  color: var(--color-text-faint);
}

.mini-bar-legend li {
  display: flex;
  align-items: center;
  gap: 4px;
}

.conference-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.conference-card {
  padding: 16px 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.conference-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.conference-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.conference-intro {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.75;
  color: var(--color-text-muted);
}

.conference-years {
  margin-top: 10px;
  font-size: 11px;
  color: var(--color-text-subtle);
}

.source-list {
  display: grid;
  gap: 14px;
}

.source-list li {
  padding-bottom: 14px;
  border-bottom: 1px solid var(--color-border-soft);
}

.source-list li:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.source-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.source-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.source-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.75;
  color: var(--color-text-muted);
}

.step-list {
  display: grid;
  gap: 16px;
  margin-top: 16px;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.step-index {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
}

.step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.step-desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.75;
  color: var(--color-text-muted);
}

.formula {
  padding: 14px 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  font-size: 14px;
  color: var(--color-text);
}

.distinction-grid,
.legend-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.legend-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.distinction-card,
.legend-card {
  padding: 14px 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.distinction-title,
.legend-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.distinction-desc,
.legend-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.group-list {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--color-text-subtle);
}

.group-list li {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

@media (max-width: 1100px) {
  .coverage-grid,
  .conference-grid,
  .legend-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .audience-grid,
  .coverage-grid,
  .conference-grid,
  .distinction-grid,
  .legend-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
