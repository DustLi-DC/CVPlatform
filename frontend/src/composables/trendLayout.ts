/**
 * 热度走势图的布局常量。
 *
 * 三处要用同一组数字：ECharts 的 `option.grid`、DOM 播放头的覆盖层定位、
 * 以及导出 GIF 时在离屏画布上手绘播放头。原先只有前两处共用（写在组件里的 GRID），
 * 加了导出之后第三处也要用——放一份在这里，避免三份定义各改各的。
 */

/** 绘图区内边距：与 option.grid 一致 */
export const TREND_GRID = { left: 56, right: 24, top: 48, bottom: 36 } as const

/** 播放头滑行时长：略短于 900ms 的播放步长，走完一格能落定再进下一格 */
export const PLAYHEAD_SLIDE_MS = 700

/** 数据点半径：当前年份放大一档，让"正在被画出来"的那个点看得见 */
export const SYMBOL_SIZE = 7
export const SYMBOL_SIZE_ACTIVE = 9.5

/** 导出 GIF 时的底部说明栏高度（像素） */
export const GIF_FOOTER_HEIGHT = 30

/** 导出 GIF 的帧率：10 fps 在"看得清生长过程"与"文件别太大"之间取平衡 */
export const GIF_FPS = 10
