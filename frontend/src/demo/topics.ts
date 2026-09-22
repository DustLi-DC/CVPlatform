/**
 * 演示用研究主题与关键词图谱数据（取自墨刀原型）。
 *
 * 阶段 1 已确认统计口径为“主题归并表（方案 A）”，主题初值在阶段 6 由真实高频词
 * 产出后回填。此处沿用原型演示主题仅为界面核对，不得作为最终主题表。
 */

import { demoCoverage } from './coverage'

export type TopicGroup = 'perception' | 'threeD' | 'multimodal' | 'none'

/** 默认展示的主题。用常量而非数组下标，避免可空类型与隐式顺序依赖。 */
export const defaultTrendTopic = '目标检测'

export interface DemoTopic {
  name: string
  group: TopicGroup
  /** 各会议各年份包含该主题的演示论文数 */
  counts: Record<string, Record<number, number>>
}

export const topicGroupLabels: Record<Exclude<TopicGroup, 'none'>, string> = {
  perception: '感知与识别',
  threeD: '三维与生成',
  multimodal: '语言与多模态',
}

export const topicGroupColors: Record<TopicGroup, string> = {
  perception: 'var(--color-group-perception)',
  threeD: 'var(--color-group-three-d)',
  multimodal: 'var(--color-group-multimodal)',
  none: 'var(--color-group-none)',
}

export const demoTrendTopics: DemoTopic[] = [
  {
    name: '目标检测',
    group: 'perception',
    counts: {
      CVPR: { 2022: 96, 2023: 98, 2024: 104, 2025: 96 },
      ICCV: { 2023: 101, 2025: 94 },
      ECCV: { 2022: 73, 2024: 78 },
    },
  },
  {
    name: '视觉语言模型',
    group: 'multimodal',
    counts: {
      CVPR: { 2022: 34, 2023: 72, 2024: 118, 2025: 142 },
      ICCV: { 2023: 56, 2025: 112 },
      ECCV: { 2022: 26, 2024: 84 },
    },
  },
  {
    name: '语义分割',
    group: 'perception',
    counts: {
      CVPR: { 2022: 88, 2023: 84, 2024: 79, 2025: 71 },
      ICCV: { 2023: 92, 2025: 80 },
      ECCV: { 2022: 69, 2024: 66 },
    },
  },
  {
    name: '三维重建',
    group: 'threeD',
    counts: {
      CVPR: { 2022: 62, 2023: 71, 2024: 76, 2025: 70 },
      ICCV: { 2023: 68, 2025: 66 },
      ECCV: { 2022: 54, 2024: 72 },
    },
  },
  {
    name: '扩散生成模型',
    group: 'threeD',
    counts: {
      CVPR: { 2022: 41, 2023: 78, 2024: 86, 2025: 83 },
      ICCV: { 2023: 64, 2025: 71 },
      ECCV: { 2022: 33, 2024: 77 },
    },
  },
  {
    name: '视频理解',
    group: 'perception',
    counts: {
      CVPR: { 2022: 70, 2023: 66, 2024: 62, 2025: 58 },
      ICCV: { 2023: 74, 2025: 63 },
      ECCV: { 2022: 52, 2024: 55 },
    },
  },
  {
    name: '自监督学习',
    group: 'perception',
    counts: {
      CVPR: { 2022: 74, 2023: 69, 2024: 57, 2025: 48 },
      ICCV: { 2023: 71, 2025: 52 },
      ECCV: { 2022: 58, 2024: 49 },
    },
  },
  {
    name: '多模态大模型',
    group: 'multimodal',
    counts: {
      CVPR: { 2022: 12, 2023: 38, 2024: 96, 2025: 128 },
      ICCV: { 2023: 29, 2025: 97 },
      ECCV: { 2022: 9, 2024: 66 },
    },
  },
  {
    name: '人体姿态估计',
    group: 'perception',
    counts: {
      CVPR: { 2022: 52, 2023: 47, 2024: 43, 2025: 38 },
      ICCV: { 2023: 50, 2025: 41 },
      ECCV: { 2022: 44, 2024: 39 },
    },
  },
  {
    name: '神经辐射场',
    group: 'threeD',
    counts: {
      CVPR: { 2022: 48, 2023: 62, 2024: 44, 2025: 31 },
      ICCV: { 2023: 54, 2025: 36 },
      ECCV: { 2022: 37, 2024: 41 },
    },
  },
  {
    name: '医学图像分割',
    group: 'perception',
    counts: {
      CVPR: { 2022: 33, 2023: 39, 2024: 46, 2025: 52 },
      ICCV: { 2023: 36, 2025: 48 },
      ECCV: { 2022: 29, 2024: 43 },
    },
  },
  {
    name: '图像分类',
    group: 'perception',
    counts: {
      CVPR: { 2022: 56, 2023: 44, 2024: 33, 2025: 26 },
      ICCV: { 2023: 48, 2025: 29 },
      ECCV: { 2022: 41, 2024: 28 },
    },
  },
  {
    name: '三维高斯泼溅',
    group: 'threeD',
    counts: {
      CVPR: { 2022: 0, 2023: 3, 2024: 68, 2025: 79 },
      ICCV: { 2023: 5, 2025: 62 },
      ECCV: { 2022: 0, 2024: 47 },
    },
  },
  {
    name: '对抗鲁棒性',
    group: 'perception',
    counts: {
      CVPR: { 2022: 38, 2023: 34, 2024: 27, 2025: 22 },
      ICCV: { 2023: 41, 2025: 26 },
      ECCV: { 2022: 31, 2024: 24 },
    },
  },
]

export interface DemoGraphEdge {
  source: string
  target: string
  /** 同篇论文共现的演示次数 */
  weight: number
}

export const demoGraphEdges: DemoGraphEdge[] = [
  { source: '目标检测', target: '语义分割', weight: 128 },
  { source: '目标检测', target: '视觉语言模型', weight: 64 },
  { source: '目标检测', target: '对抗鲁棒性', weight: 36 },
  { source: '语义分割', target: '医学图像分割', weight: 58 },
  { source: '语义分割', target: '三维重建', weight: 44 },
  { source: '视觉语言模型', target: '多模态大模型', weight: 96 },
  { source: '多模态大模型', target: '扩散生成模型', weight: 52 },
  { source: '扩散生成模型', target: '图像分类', weight: 40 },
  { source: '三维重建', target: '神经辐射场', weight: 88 },
  { source: '神经辐射场', target: '三维高斯泼溅', weight: 61 },
  { source: '三维重建', target: '三维高斯泼溅', weight: 74 },
  { source: '视频理解', target: '自监督学习', weight: 69 },
  { source: '视频理解', target: '人体姿态估计', weight: 47 },
  { source: '自监督学习', target: '图像分类', weight: 72 },
  { source: '视觉语言模型', target: '视频理解', weight: 43 },
  { source: '人体姿态估计', target: '三维重建', weight: 31 },
  { source: '对抗鲁棒性', target: '图像分类', weight: 29 },
  { source: '医学图像分割', target: '自监督学习', weight: 22 },
]

/** 关键词下拉选项（原型使用固定列表；阶段 3 起改为按统计结果提供） */
export const demoKeywordOptions = demoTrendTopics.map((topic) => topic.name)

export function findDemoTopic(name: string): DemoTopic | undefined {
  return demoTrendTopics.find((topic) => topic.name === name)
}

/** 演示：某会议年份的样本量；该组合无数据时返回 null（对应原型的灰色缺口） */
export function demoConferenceYearSample(conference: string, year: number): number | null {
  const entry = demoCoverage.find(
    (item) => item.conference === conference && item.year === year,
  )
  return entry ? entry.papers : null
}

/** 演示：主题在某会议某年份的论文数；无数据返回 null，有数据但为 0 返回 0 */
export function demoTopicCount(topic: DemoTopic, conference: string, year: number): number | null {
  const byConference = topic.counts[conference]
  if (!byConference) return null
  const value = byConference[year]
  return typeof value === 'number' ? value : null
}
