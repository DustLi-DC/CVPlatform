<script setup lang="ts">
/**
 * 页面 6 · 关于平台（对应原型 06_about）。
 * 说明数据来源、覆盖范围、关键词方法、统计口径与图谱读法。
 * 数据来源一节按阶段 1 的实测结论书写：实际可用的来源是 CVF Open Access 与 ECVA，
 * 在线兜底为 OpenAlex；DBLP 实测不可用，因此不在此声明使用 DBLP。
 */
import { computed, onMounted, ref } from 'vue'

import ChartContainer from '../components/ChartContainer.vue'
import DemoNotice from '../components/DemoNotice.vue'
import PageHeader from '../components/PageHeader.vue'
import { fetchCoverage } from '../api/statsApi'
import { topicGroupColors, topicGroupLabels } from '../types/stats'
import { conferenceColors, type Conference } from '../types/paper'
import type { StatsCoverageDetail } from '../types/stats'

/**
 * 覆盖数据来自 `GET /api/stats/coverage`（库中实时计算），不再使用演示数据：
 * 「18,149 篇」这类演示数字必须替换为按实际覆盖统计的值。
 */
const coverage = ref<StatsCoverageDetail | null>(null)
const coverageError = ref('')

const conferenceYears = computed(() =>
  [...new Set((coverage.value?.covered ?? []).map((item) => item.year))].sort(),
)

/** 每年纳入分析的论文数之和（就是柱高要画的那个量） */
const yearTotals = computed(() => {
  const map = new Map<number, number>()
  for (const item of coverage.value?.covered ?? []) {
    map.set(item.year, (map.get(item.year) ?? 0) + item.analysis_papers)
  }
  return map
})

/**
 * 每根柱子的高度：该年各会议之和 ÷ **各年之和的最大值**。
 *
 * 注意分母必须是「按年求和后的最大值」——早先误用「单个会议的最大篇数」，
 * 于是三会议之和超过它时算出 height:126% 这种超过轨道的高度，柱子顶部被容器裁掉。
 * 乘 92% 留出顶部余量，避免最高柱贴到轨道圆角上沿。
 */
function barHeight(year: number): string {
  const maxYearTotal = Math.max(...yearTotals.value.values(), 1)
  const total = yearTotals.value.get(year) ?? 0
  return `${Math.max(6, Math.round((total / maxYearTotal) * 92))}%`
}

function sampleOf(conference: string, year: number): number | null {
  const found = (coverage.value?.covered ?? []).find(
    (item) => item.conference === conference && item.year === year,
  )
  return found ? found.analysis_papers : null
}

/** 来源标识 → 展示名与官网地址（外部事实均可核对） */
const sourceMeta: Record<string, { name: string; url: string }> = {
  cvf: { name: 'CVF Open Access', url: 'https://openaccess.thecvf.com/' },
  ecva: { name: 'ECVA', url: 'https://www.ecva.net/' },
  openalex: { name: 'OpenAlex', url: 'https://openalex.org/' },
  manual: { name: '手工录入', url: '' },
  dataset: { name: '课程数据集', url: '' },
}

const sourceRows = computed(() =>
  (coverage.value?.by_source ?? []).map((item) => ({
    ...item,
    name: sourceMeta[item.source]?.name ?? item.source,
    url: sourceMeta[item.source]?.url ?? '',
  })),
)

/**
 * 范围提示由接口数据拼出，不写死数字：覆盖范围变了（例如纳入更多年份或补上 ECCV 2026）
 * 提示会跟着变，避免出现「数据早就换了、说明还写抽样 200 篇」这种过期文案。
 */
const scopeNotice = computed(() => {
  const summary = coverageSummary.value
  if (!summary) return ''
  const parts: string[] = [
    `本平台覆盖 ${summary.years}（${summary.combos} 个会议年份、${summary.records} 篇）：`,
  ]
  if (summary.fullYears) {
    parts.push(
      `其中 ${summary.fullYears} 个年份是 2020 年及以后的完整论文集（该届全部录用论文），`,
    )
  }
  if (summary.sampledYears) {
    parts.push(
      `另有 ${summary.sampledYears} 个年份为抽样（每组合最多 ${summary.sampleLimit} 篇），`,
    )
  }
  parts.push(
    '2020 年之前未采集；论文文本只有题目与摘要。' +
      '这里的榜单、图谱与曲线描述的是这个范围，不构成对整个领域研究现状的结论。',
  )
  return parts.join('')
})

const coverageSummary = computed(() => {
  const data = coverage.value
  if (!data) return null
  const missing = data.missing_conference_years
    .map((item) => `${item.conference} ${item.year}`)
    .join('、')
  const kinds = data.coverage_kinds ?? { full: 0, partial: 0, sampled: 0, unknown: 0 }
  return {
    years: conferenceYears.value.length
      ? `${conferenceYears.value[0]} — ${conferenceYears.value[conferenceYears.value.length - 1]}`
      : '—',
    combos: data.totals.conference_years,
    records: data.totals.records,
    analysis: data.totals.analysis_papers,
    missing,
    kinds,
    fullYears: (data.full_coverage_years ?? []).length,
    sampledYears: kinds.sampled + kinds.partial,
    // 数据集列表：只展示真正按完整论文集导入的（limit 为空）
    fullDatasets: (data.datasets ?? []).filter((item) => item.limit === null),
    sampled: data.sampled,
    sampleLimit: data.sample_limit_per_conference_year,
    abstractRate: (() => {
      const present = data.covered.reduce((sum, item) => sum + item.abstract_present, 0)
      return data.totals.records
        ? Math.round((present / data.totals.records) * 1000) / 10
        : null
    })(),
  }
})

onMounted(async () => {
  try {
    coverage.value = await fetchCoverage()
  } catch (error) {
    coverageError.value = '加载覆盖数据失败，请确认后端服务已启动后刷新页面。'
    console.error('加载覆盖数据失败：', error)
  }
})

const conferenceMeta: {
  name: Conference
  cadence: string
  intro: string
  years: string
  /** 官方入口，供读者核对会议与年份规律 */
  sourceUrl: string
  sourceLabel: string
}[] = [
  {
    name: 'CVPR',
    cadence: '每年举办',
    sourceUrl: 'https://openaccess.thecvf.com/CVPR2024',
    sourceLabel: 'openaccess.thecvf.com',
    // 长句拆成多段拼接：不改变渲染结果，同时避免超长行
    intro:
      'IEEE/CVF Conference on Computer Vision and Pattern Recognition，'
      + '计算机视觉领域规模最大的年度会议之一，投稿与录用数量长期居前，'
      + '方向覆盖检测、分割、生成、多模态等。',
    years: '2022 / 2023 / 2024 / 2025',
  },
  {
    name: 'ICCV',
    cadence: '奇数年举办',
    sourceUrl: 'https://openaccess.thecvf.com/ICCV2023',
    sourceLabel: 'openaccess.thecvf.com',
    intro:
      'IEEE/CVF International Conference on Computer Vision，'
      + '两年一次的旗舰会议之一，通常在奇数年举办，'
      + '论文平均篇幅较长，方法类与理论类工作比例相对更高。',
    years: '仅奇数年有数据',
  },
  {
    name: 'ECCV',
    cadence: '偶数年举办',
    sourceUrl: 'https://www.ecva.net/papers.php',
    sourceLabel: 'ecva.net',
    intro:
      'European Conference on Computer Vision，两年一次的欧洲旗舰会议，'
      + '通常在偶数年举办，可由 ECVA 的会议论文页核对。',
    years: '仅偶数年有数据',
  },
]

/** 标题区说明较长，放在脚本里拼接，避免模板属性出现超长行 */
const pageDescription =
  '这一页解释平台为什么这样统计。如果榜单和曲线里的数字让你有点不确定，先看这里：'
  + '数据从哪来、关键词怎么抽出来、热度怎么算，以及为什么这里的结果只能当作一个观察样本。'

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
    desc:
      '同义表达（如 object detection / object detector）会归并到同一个主题；'
      + '论文自带的关键词作为「来源提供的关键词」单独保留，不与系统提取结果混在一起。',
  },
]

const dataSources = [
  {
    name: 'CVF Open Access',
    scope: 'CVPR、ICCV 的论文题目、作者、摘要与原文链接',
    desc: '会议官方开放获取页面。论文题目与作者取自会议索引页，摘要取自逐篇详情页。',
    url: 'https://openaccess.thecvf.com/',
  },
  {
    name: 'ECVA 会议论文页',
    scope: 'ECCV 的论文题目、作者、摘要与原文链接',
    desc: 'ECCV 官方论文入口，按年份汇总。CVF 不收录 ECCV（实测该路径返回 404），因此 ECCV 的样本只能来自 ECVA。',
    url: 'https://www.ecva.net/papers.php',
  },
  {
    name: 'OpenAlex',
    scope: '在线兜底检索与文献元数据交叉核对',
    desc: '本地论文库未命中时按题目检索公开文献元数据（含摘要倒排索引还原），返回候选后必须由使用者确认，避免静默匹配错误论文。',
    url: 'https://openalex.org/',
  },
  {
    name: '会议年份事实核对',
    scope: '会议周期与年份规律',
    desc: 'ICCV 奇数年、ECCV 偶数年、CVPR 每年举办，均可在上面的官方入口按年份路径核对（如 /CVPR2024 可访问、ECCV 年份在 ECVA 的 papers 页按年份列出）。',
    url: '',
  },
]
</script>

<template>
  <div>
    <PageHeader
      eyebrow="页面 6 / 关于平台"
      title="关于 CVPlatform"
      :description="pageDescription"
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
        <template v-if="scopeNotice">{{ scopeNotice }}</template>
        <template v-else>数据范围正在加载，加载完成后这里会说明本次分析覆盖的会议年份与论文数。</template>
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
          <dd>{{ coverageSummary ? coverageSummary.years : '—' }}</dd>
        </div>
        <div>
          <dt>会议年份组合</dt>
          <dd>
            {{ coverageSummary ? coverageSummary.combos : '—' }} 个
            <span class="coverage-note">（ICCV 奇数年 / ECCV 偶数年）</span>
          </dd>
        </div>
        <div>
          <dt>论文样本量</dt>
          <dd>
            <template v-if="coverageSummary">
              {{ coverageSummary.records }} 篇记录，其中
              <strong>{{ coverageSummary.analysis }} 篇</strong>进入分析分母
            </template>
            <template v-else>—</template>
          </dd>
        </div>
        <div>
          <dt>摘要可用比例</dt>
          <dd>
            {{ coverageSummary && coverageSummary.abstractRate !== null ? `${coverageSummary.abstractRate}%` : '—' }}
          </dd>
        </div>
        <div>
          <dt>关键词规则版本</dt>
          <dd>{{ coverage?.keyword_ruleset_version ?? '—' }}</dd>
        </div>
        <div>
          <dt>主题表版本</dt>
          <dd>{{ coverage?.topic_ruleset_version ?? '—' }}</dd>
        </div>
      </dl>

      <p v-if="coverageError" class="field-error" role="alert">{{ coverageError }}</p>
      <template v-else-if="coverageSummary">
        <p class="section-text">
          <strong>数据性质</strong>：
          <template v-if="coverageSummary.fullYears">
            其中 {{ coverageSummary.fullYears }} 个会议年份是<strong>完整论文集</strong>
            （2020 年及以后的会议，逐届全部录用论文），这些年份的占比就是该届录用论文中的比例。
          </template>
          <template v-if="coverageSummary.sampledYears">
            另有 {{ coverageSummary.sampledYears }} 个会议年份为抽样（每组合最多
            {{ coverageSummary.sampleLimit }} 篇），只表示样本内的相对热度。
          </template>
          <template v-if="coverageSummary.missing">
            目标范围内还没采集到数据的组合：{{ coverageSummary.missing }}。
          </template>
        </p>

        <div v-if="coverageSummary.fullDatasets.length" class="dataset-block">
          <h3 class="dataset-title">完整论文集的数据集与版本</h3>
          <p class="section-text">
            下列数据集来自 HuggingFace 上公开的会议论文集镜像，逐届一个数据集；
            每篇论文同时保留官方原文链接（CVF / ECVA），可逐条回溯到会议页面。
            括号中的修订号可以精确复现「这批数据来自哪个版本」。
          </p>
          <ul class="dataset-list">
            <li v-for="item in coverageSummary.fullDatasets" :key="item.dataset">
              <a
                :href="`https://huggingface.co/datasets/${item.dataset}`"
                target="_blank"
                rel="noopener noreferrer"
              >{{ item.dataset }}</a>
              <span class="dataset-meta">
                {{ item.rows }} 篇 · 导入 {{ (item.imported_at ?? '').slice(0, 10) }}
                <template v-if="item.revision"> · 修订 {{ item.revision.slice(0, 8) }}</template>
              </span>
            </li>
          </ul>
        </div>
      </template>

      <ChartContainer
        class="coverage-chart"
        title="各会议年份纳入分析的论文数"
        subtitle="柱高表示该年份三个会议纳入分析论文数之和；柱下方的会议标签给出该会议该年份的实际篇数，「无数据」表示该组合没有记录，不做零值填充。"
        unit="单位：篇"
        height="250px"
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
          <p class="conference-years">
            官方入口：
            <a :href="meta.sourceUrl" target="_blank" rel="noopener noreferrer">{{ meta.sourceLabel }}</a>
          </p>
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
          <p v-if="item.url" class="source-url">
            官方入口：<a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.url }}</a>
          </p>
        </li>
      </ul>
      <p v-if="sourceRows.length" class="section-text">
        <strong>本库论文的来源标识分布</strong>（按来源去重计数）：
        <span v-for="(row, index) in sourceRows" :key="row.source">
          {{ index > 0 ? '、' : '' }}{{ row.name }} {{ row.papers }} 篇
        </span>。
        每篇论文的详情页都会显示它自己的来源标识与获取时间，可逐条核对。
      </p>
      <p class="section-text">
        <strong>实测不可用的来源</strong>：DBLP 在核对时返回反爬页面（Anubis），即使带浏览器标识也被拦截，
        因此没有接入；Semantic Scholar 的公开接口在测试中触发限流，只作为可选项保留说明，不作为主来源。
      </p>
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
      <p class="section-text">
        <strong>统计只使用系统提取的关键词</strong>，并经主题归并（主题表
        {{ coverage?.topic_ruleset_version ?? 'topic-v3' }}：{{ coverage?.topic_total ?? '—' }} 个主题、
        {{ coverage?.topic_alias_total ?? '—' }} 条别名，见仓库内 backend/app/data/topics_v1.json）。
        论文自带的作者关键词只作展示，
        不参与 Top 10、图谱与趋势，避免两种来源混在一起改变口径。
        当前关键词规则版本为 <strong>{{ coverage?.keyword_ruleset_version ?? 'kw-v4' }}</strong>，
        停用词、短语阈值等规则变化时会提升版本号并按新版本重算。
      </p>
      <p class="section-text">
        过短的常见词（如 image、data、learning）即使高频也不单独作为关键词，
        它们的方向含义由短语承载（如 image generation、contrastive learning）；
        映射不到任何主题的关键词如实保留并在界面上标为「未归类」，不强行塞进某个主题。
      </p>
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
          <h3 class="distinction-title">该届不举办</h3>
          <p class="distinction-desc">
            ICCV 只有奇数年、ECCV 只有偶数年，不举办的年份没有会议。趋势图中曲线<strong>跨过该年份连线</strong>，
            并用浅色区间标注，<strong>不画成 0</strong>。
          </p>
        </div>
        <div class="distinction-card">
          <h3 class="distinction-title">该届举办了但没采到数据</h3>
          <p class="distinction-desc">
            例如 ECCV 2026 的摘要在核对时只有 71%（数据仍在补齐）而未纳入。趋势图中<strong>断开曲线</strong>并标注
            「无数据」，与「热度为 0」区分开。
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
        这里看到的一切都来自一个有限范围：三个会议、2020 年及以后（CVPR 每年，ICCV 奇数年、ECCV 偶数年），
        文本只含题目与摘要。会议录用结构本身在变化，
        关键词抽取也会漏掉用不同措辞表达的同类工作，因此某个方向在某条曲线上的升降，只能说明「在这个样本里它出现得多或少了」，
        不能直接推导出整个计算机视觉领域的研究结论。如果要据此选择研究方向，建议把这里当作线索的起点：
        挑出 2—3 个方向，再去读会议论文原文与综述做交叉验证。
      </p>
    </section>
  </div>
</template>

<style scoped>
.dataset-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-soft);
}

.dataset-title {
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.dataset-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
  font-size: 13px;
}

.dataset-list a {
  color: var(--color-primary);
}

.dataset-meta {
  margin-left: 8px;
  color: var(--color-text-subtle);
  font-size: 12px;
}

.source-url {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.source-url a {
  color: var(--color-primary);
}

.coverage-note {
  color: var(--color-text-subtle);
  font-size: 12px;
}

.field-error {
  margin-top: 12px;
  font-size: 13px;
  color: var(--color-danger, #b91c1c);
}

.conference-years a {
  color: var(--color-primary);
}

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
  /* 不再用 height:100%：列里除了轨道还有年份与三行图例，
     百分百高度会让轨道被撑到容器之外，被容器的 overflow:hidden 裁掉顶部 */
  padding: 16px 24px 12px;
}

.mini-bar-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.mini-bar-track {
  display: flex;
  align-items: flex-end;
  width: 100%;
  max-width: 64px;
  /* 固定高度：柱高按这个高度的百分比计算，容器高度按它 + 年份 + 图例确定 */
  height: 120px;
  flex: none;
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
