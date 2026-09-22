/**
 * 演示数据集中管理。
 *
 * 重要：本目录下所有数值都是**界面演示数据**，取自已确认的墨刀原型，
 * 用于在接口接入前核对布局、信息层级与交互。它不代表真实采集结果，
 * 也不等同于阶段 1 确定的抽样式真实样本（每会议年份约 200 篇）。
 *
 * 接入顺序：阶段 4 起论文管理与详情改用后端接口，阶段 6 起覆盖范围与导入
 * 任务改用后端接口，阶段 8/9 起统计与趋势改用后端接口。届时逐项删除本目录
 * 中对应的演示数据，不允许把演示值当作真实统计呈现。
 */

export interface DemoCoverage {
  conference: string
  year: number
  papers: number
}

/** 演示用的会议年份样本量（原型数值，按真实会议年份规律：ICCV 奇数年、ECCV 偶数年） */
export const demoCoverage: DemoCoverage[] = [
  { conference: 'CVPR', year: 2022, papers: 2088 },
  { conference: 'CVPR', year: 2023, papers: 2360 },
  { conference: 'CVPR', year: 2024, papers: 2719 },
  { conference: 'CVPR', year: 2025, papers: 2871 },
  { conference: 'ICCV', year: 2023, papers: 2160 },
  { conference: 'ICCV', year: 2025, papers: 2412 },
  { conference: 'ECCV', year: 2022, papers: 1650 },
  { conference: 'ECCV', year: 2024, papers: 1889 },
]

export const demoConferences = ['CVPR', 'ICCV', 'ECCV'] as const

export type DemoConference = (typeof demoConferences)[number]

/** 演示年份范围。用显式常量而非数组下标取值，避免在 noUncheckedIndexedAccess 下出现可空类型。 */
export const demoYearFirst = 2022
export const demoYearLast = 2025
export const demoYears: readonly number[] = [2022, 2023, 2024, 2025]

/** 演示数据统一后缀，出现在任何由演示数据计算出的数值旁 */
export const DEMO_SUFFIX = '（演示）'

/** 未接入后端的操作提示：用于写入类动作，避免让人误以为已持久化 */
export const NOT_CONNECTED_NOTICE = '界面演示：本次操作仅在本页内存中生效，尚未接入后端接口。'

export function isDemoConference(value: string): value is DemoConference {
  return (demoConferences as readonly string[]).includes(value)
}
