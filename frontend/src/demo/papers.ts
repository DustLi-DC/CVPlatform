/**
 * 首页「关键词相关论文」抽屉的演示数据。
 *
 * 说明：论文列表与详情已接入真实接口（阶段 4），本文件只服务于首页抽屉。
 * 抽屉的正式数据源是统计接口（`GET /api/stats/keyword/{name}/papers`），在阶段 8 接入，
 * 因此这里保留**仅够渲染抽屉的元素**：题目、会议、年份、编号。
 *
 * 刻意不再存放摘要与关键词明细——那些字段此前是原型时代的虚构内容，
 * 既然没有真正采集过，就不应该以"论文数据"的形态存在。
 * 用于抽屉内按主题筛选的 `topics` 是演示用映射，不是真实的关键词抽取结果。
 */
import type { Conference } from '../types/paper'

export interface DemoPaperRef {
  id: number
  code: string
  title: string
  conference: Conference
  year: number
  /** 演示用的主题归属，仅用于抽屉筛选示例论文 */
  topics: string[]
}

export const demoDrawerPapers: DemoPaperRef[] = [
  {
    id: 9001,
    code: 'CVPR-2024-1188',
    title: 'DETRs Beat YOLOs on Real-time Object Detection',
    conference: 'CVPR',
    year: 2024,
    topics: ['目标检测', '视频理解'],
  },
  {
    id: 9002,
    code: 'ECCV-2024-0233',
    title:
      'Grounding DINO: Marrying DINO with Grounded Pre-Training for Open-Set Object Detection',
    conference: 'ECCV',
    year: 2024,
    topics: ['目标检测', '视觉语言模型', '多模态大模型'],
  },
  {
    id: 9003,
    code: 'ICCV-2023-0064',
    title: 'Segment Anything',
    conference: 'ICCV',
    year: 2023,
    topics: ['语义分割', '目标检测', '医学图像分割', '视觉语言模型'],
  },
  {
    id: 9004,
    code: 'ECCV-2024-0917',
    title: '2D Gaussian Splatting for Geometrically Accurate Radiance Fields',
    conference: 'ECCV',
    year: 2024,
    topics: ['三维重建', '三维高斯泼溅', '神经辐射场'],
  },
  {
    id: 9005,
    code: 'CVPR-2024-0308',
    title:
      'InternVL: Scaling up Vision Foundation Models and Aligning for Generic Visual-Linguistic Tasks',
    conference: 'CVPR',
    year: 2024,
    topics: ['多模态大模型', '视觉语言模型'],
  },
  {
    id: 9006,
    code: 'CVPR-2024-0721',
    title: 'Depth Anything: Unleashing the Power of Large-Scale Unlabeled Data',
    conference: 'CVPR',
    year: 2024,
    topics: ['三维重建', '自监督学习'],
  },
  {
    id: 9007,
    code: 'ICCV-2023-0562',
    title: 'Zip-NeRF: Anti-Aliased Grid-Based Neural Radiance Fields',
    conference: 'ICCV',
    year: 2023,
    topics: ['神经辐射场', '三维重建'],
  },
  {
    id: 9008,
    code: 'ECCV-2024-0660',
    title: 'CoTracker: It is Better to Track Together',
    conference: 'ECCV',
    year: 2024,
    topics: ['视频理解', '人体姿态估计'],
  },
  {
    id: 9009,
    code: 'CVPR-2022-0418',
    title: 'Masked Autoencoders Are Scalable Vision Learners',
    conference: 'CVPR',
    year: 2022,
    topics: ['自监督学习', '图像分类', '对抗鲁棒性'],
  },
  {
    id: 9010,
    code: 'CVPR-2022-1102',
    title: 'High-Resolution Image Synthesis with Latent Diffusion Models',
    conference: 'CVPR',
    year: 2022,
    topics: ['扩散生成模型', '图像分类'],
  },
  {
    id: 9011,
    code: 'ICCV-2023-0755',
    title: 'Adding Conditional Control to Text-to-Image Diffusion Models',
    conference: 'ICCV',
    year: 2023,
    topics: ['扩散生成模型', '视觉语言模型'],
  },
  {
    id: 9012,
    code: 'ECCV-2024-0451',
    title: 'Sapiens: Foundation for Human Vision Models',
    conference: 'ECCV',
    year: 2024,
    topics: ['人体姿态估计', '视觉语言模型', '多模态大模型'],
  },
]
