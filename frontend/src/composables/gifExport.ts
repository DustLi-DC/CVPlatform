/**
 * 热度走势动画 → GIF。
 *
 * 页面上这个动画由三部分组成，而 GIF 只能从画布取像素，所以这里要合成：
 *   1) ECharts 画布（曲线、坐标轴、缺失/不举办区间）——直接 drawImage；
 *   2) 播放头（光带、虚线、圆点、年份标签）——它是 DOM 覆盖层，不在画布里，
 *      按当前横坐标在离屏画布上手绘，视觉与 CSS 版保持一致；
 *   3) 底部说明栏（主题 · 年份 · 单位 · 会议色例）——GIF 发出去后脱离页面，
 *      少了这行就不知道画的是哪个主题、颜色代表哪个会议。
 *
 * 编码用 gifenc（MIT、无传递依赖、约 5 KB）：按需 `import('gifenc')`，
 * 只有真正点"导出 GIF"时才下载这段代码，主包与图表页首屏不受影响。
 *
 * 两个视图各有一条合成路径（榜单视图没有画布，见文末说明）：
 *   - 热度趋势曲线 → composeFrame（画布 + 手绘播放头 + 说明栏）；
 *   - 年度 Top 10 演变 → readRankSnapshot + composeRankFrame（手绘榜单）。
 *
 * 调色板取中间帧共用一份：曲线与背景配色全程固定，共用既省体积也不会逐帧换色闪一下。
 */
import { resolveCssColor } from './colors'
import { GIF_FOOTER_HEIGHT, TREND_GRID } from './trendLayout'

export interface GifCaption {
  /** 顶部／底部的主题名，如「三维重建与辐射场」 */
  title: string
  /** 当前年份文本 */
  year: string
  /** 纵轴单位，如「占比（%）」 */
  unit: string
  /** 会议色例（颜色可以是设计令牌，合成时会解析） */
  legend: { label: string; color: string }[]
}

export interface GifFrameInput {
  /** 图表画布 */
  canvas: HTMLCanvasElement
  /** 播放头横坐标（相对画布左边缘，单位与画布像素一致）；null 表示当前不显示 */
  playheadX: number | null
}

/** 导出宽度上限：画布在高分屏上可能是 2 倍像素，限制一下免得 GIF 过大 */
const MAX_WIDTH = 960
/** 播放头光带宽度与圆点半径，与组件里的 CSS 取值保持一致 */
const BAND_WIDTH = 34
const DOT_RADIUS = 3.5
const FONT_STACK =
  '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", system-ui, -apple-system, sans-serif'

/** 在离屏画布上合成一帧：白底 + 图表画布 + 手绘播放头 + 底部说明栏 */
export function composeFrame(input: GifFrameInput, caption: GifCaption): HTMLCanvasElement {
  const source = input.canvas
  const scale = Math.min(1, MAX_WIDTH / source.width)
  const width = Math.max(1, Math.round(source.width * scale))
  const chartHeight = Math.max(1, Math.round(source.height * scale))

  const frame = document.createElement('canvas')
  frame.width = width
  frame.height = chartHeight + GIF_FOOTER_HEIGHT
  const ctx = frame.getContext('2d', { willReadFrequently: true })
  if (!ctx) return frame

  // 页面上图表卡片是白底、画布本身透明；GIF 不做半透明叠加，先铺白底再画
  ctx.fillStyle = resolveCssColor('var(--color-surface)')
  ctx.fillRect(0, 0, frame.width, frame.height)
  ctx.drawImage(source, 0, 0, width, chartHeight)

  if (input.playheadX !== null) {
    drawPlayhead(ctx, {
      x: input.playheadX * scale,
      top: TREND_GRID.top * scale,
      bottom: chartHeight - TREND_GRID.bottom * scale,
      year: caption.year,
    })
  }
  drawFooter(ctx, width, chartHeight, caption)
  return frame
}

/** 手绘播放头：与 CSS 版同样的光带、虚线、圆点与年份标签 */
function drawPlayhead(
  ctx: CanvasRenderingContext2D,
  options: { x: number; top: number; bottom: number; year: string },
): void {
  const { x, top, bottom, year } = options
  const primary = resolveCssColor('var(--color-primary)')

  const band = ctx.createLinearGradient(0, top, 0, bottom)
  band.addColorStop(0, 'rgba(29, 78, 216, 0.12)')
  band.addColorStop(0.55, 'rgba(29, 78, 216, 0.05)')
  band.addColorStop(1, 'rgba(29, 78, 216, 0)')
  ctx.fillStyle = band
  ctx.fillRect(x - BAND_WIDTH / 2, top, BAND_WIDTH, bottom - top)

  ctx.save()
  ctx.setLineDash([4, 4])
  ctx.strokeStyle = primary
  ctx.globalAlpha = 0.75
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(Math.round(x) + 0.5, top)
  ctx.lineTo(Math.round(x) + 0.5, bottom)
  ctx.stroke()
  ctx.restore()

  ctx.beginPath()
  ctx.arc(x, top, DOT_RADIUS, 0, Math.PI * 2)
  ctx.fillStyle = primary
  ctx.fill()

  ctx.font = `600 11px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'
  ctx.fillStyle = primary
  ctx.fillText(year, x, top - 6)
}

/** 底部说明栏：左侧主题与年份，右侧会议色例（GIF 离开页面后仍能读懂） */
function drawFooter(
  ctx: CanvasRenderingContext2D,
  width: number,
  top: number,
  caption: GifCaption,
): void {
  ctx.fillStyle = resolveCssColor('var(--color-surface-muted)')
  ctx.fillRect(0, top, width, GIF_FOOTER_HEIGHT)
  ctx.strokeStyle = resolveCssColor('var(--color-border)')
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(0, top + 0.5)
  ctx.lineTo(width, top + 0.5)
  ctx.stroke()

  const middle = top + GIF_FOOTER_HEIGHT / 2
  ctx.textBaseline = 'middle'
  ctx.textAlign = 'left'
  ctx.fillStyle = resolveCssColor('var(--color-text-strong)')
  ctx.font = `600 12px ${FONT_STACK}`
  const title = `${caption.title} · ${caption.year}`
  ctx.fillText(title, 12, middle)

  // 会议色例从右往左排，避免与左侧标题重叠
  ctx.textAlign = 'right'
  ctx.font = `11px ${FONT_STACK}`
  let right = width - 12
  for (const item of [...caption.legend].reverse()) {
    const color = resolveCssColor(item.color)
    ctx.fillStyle = resolveCssColor('var(--color-text-muted)')
    ctx.fillText(item.label, right, middle)
    right -= ctx.measureText(item.label).width + 7
    ctx.beginPath()
    ctx.arc(right - 4, middle, 4, 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.fill()
    right -= 18
    if (right < width / 2) break // 窄图时只保留右侧能看到的那几个
  }

  ctx.textAlign = 'left'
  ctx.font = `11px ${FONT_STACK}`
  ctx.fillStyle = resolveCssColor('var(--color-text-subtle)')
  ctx.fillText(`单位：${caption.unit}`, 12 + ctx.measureText(title).width + 14, middle)
}

export interface EncodeGifOptions {
  /** 帧率：每帧延时 = 1000 / fps 毫秒 */
  fps: number
  /** 编码进度回调（已编码帧数 / 总帧数） */
  onProgress?: (done: number, total: number) => void
}

/** 把合成好的帧编码成 GIF（首帧写全局调色板，后续帧复用；末帧多停一拍便于看清完整曲线） */
export async function encodeGif(
  frames: HTMLCanvasElement[],
  options: EncodeGifOptions,
): Promise<Blob> {
  const first = frames[0]
  if (!first) throw new Error('没有可编码的帧')
  const { GIFEncoder, quantize, applyPalette } = await import('gifenc')

  const width = first.width
  const height = first.height
  const sampleFrame = frames[Math.floor(frames.length / 2)] ?? first
  const sampleCtx = sampleFrame.getContext('2d', { willReadFrequently: true })
  if (!sampleCtx) throw new Error('取样帧不可读')
  const palette = quantize(sampleCtx.getImageData(0, 0, width, height).data, 256)

  const gif = GIFEncoder()
  const delay = Math.max(20, Math.round(1000 / options.fps))
  frames.forEach((frame, index) => {
    const ctx = frame.getContext('2d', { willReadFrequently: true })
    if (!ctx) return
    const indexed = applyPalette(ctx.getImageData(0, 0, width, height).data, palette)
    const isLast = index === frames.length - 1
    gif.writeFrame(indexed, width, height, {
      delay: isLast ? delay * 8 : delay,
      // 首帧必须给调色板（它会写成全局调色板），后续帧省略即复用
      ...(index === 0 ? { palette, repeat: 0 } : {}),
    })
    options.onProgress?.(index + 1, frames.length)
  })
  gif.finish()

  // 复制一份再取 buffer：gifenc 返回的 Uint8Array 视图类型与 BlobPart 不完全匹配
  const bytes = new Uint8Array(gif.bytes())
  return new Blob([bytes.buffer], { type: 'image/gif' })
}

/** 触发浏览器下载（objectURL 延迟释放：立刻 revoke 在部分浏览器会打断下载） */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/* ------------------------------------------------------------------ 榜单视图
 *
 * 「年度 Top 10 演变」没有图表画布（榜单是 DOM/CSS 实现的），所以这一路
 * 从 DOM 读出**当前这一瞬间**的行状态再画到离屏画布：
 * 条宽读计算宽度、行位读实时偏移，因此过渡进行中的中间状态也能被记录，
 * 导出的 GIF 与页面上看到的排名/条长变化一致。
 */

/** 榜单帧尺寸与行数上限：固定尺寸才能编码成 GIF（各帧必须同宽高） */
const RANK_FRAME_WIDTH = 760
const RANK_MAX_ROWS = 10
const RANK_HEADER_HEIGHT = 44
const RANK_FOOTER_HEIGHT = 30
const RANK_ROW_HEIGHT = 48
const RANK_SIDE_PADDING = 16
const RANK_LABEL_X = 52
const RANK_BAR_HEIGHT = 8

export interface RankRowSnapshot {
  label: string
  countText: string
  /** 条形颜色（取自计算样式，已是 rgb() 形式） */
  color: string
  /** 条形宽度占轨道的比例 0..1（含过渡中间值） */
  barRatio: number
  /** 行顶端相对榜单顶部的偏移（像素，含 FLIP 过渡中间值） */
  offsetY: number
  /** 行高（像素） */
  height: number
}

export interface RankSnapshot {
  rows: RankRowSnapshot[]
  /** 卡片宽度（CSS 像素），用于把 DOM 尺寸换算到画布坐标 */
  width: number
  title: string
  year: string
  /** 卡片底部的口径行（分母 / 记录数 / 主题数） */
  footer: string
}

/** 从榜单卡片读一帧快照；没有榜单列表时返回 null（该年份可能没有数据） */
export function readRankSnapshot(
  card: HTMLElement,
  meta: { title: string; year: string },
): RankSnapshot | null {
  const list = card.querySelector<HTMLElement>('.rank-list')
  if (!list) return null
  const listTop = list.getBoundingClientRect().top
  const rows: RankRowSnapshot[] = [...list.querySelectorAll('li')].map((item) => {
    const bar = item.querySelector<HTMLElement>('.rank-bar')
    const track = item.querySelector<HTMLElement>('.rank-track')
    const rowRect = item.getBoundingClientRect()
    const trackWidth = track?.getBoundingClientRect().width ?? 0
    const barWidth = bar?.getBoundingClientRect().width ?? 0
    return {
      label: item.querySelector('.rank-label')?.textContent?.trim() ?? '',
      countText: item.querySelector('.rank-count')?.textContent?.replace(/\s+/g, ' ').trim() ?? '',
      color: bar ? getComputedStyle(bar).backgroundColor : 'transparent',
      barRatio: trackWidth > 0 ? Math.min(1, barWidth / trackWidth) : 0,
      offsetY: rowRect.top - listTop,
      height: rowRect.height,
    }
  })
  return {
    rows,
    width: card.getBoundingClientRect().width,
    title: meta.title,
    year: meta.year,
    footer: card.querySelector('.rank-footer span')?.textContent?.trim() ?? '',
  }
}

/** 文字超出可用宽度时截断并加省略号（榜单里主题名可能很长） */
function drawClippedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
): void {
  if (ctx.measureText(text).width <= maxWidth) {
    ctx.fillText(text, x, y)
    return
  }
  let clipped = text
  while (clipped.length > 1 && ctx.measureText(`${clipped}…`).width > maxWidth) {
    clipped = clipped.slice(0, -1)
  }
  ctx.fillText(`${clipped}…`, x, y)
}

/** 把一帧榜单快照画成画布：标题 + 排名行（序号/主题/条数/条）+ 口径行 */
export function composeRankFrame(snapshot: RankSnapshot): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = RANK_FRAME_WIDTH
  canvas.height = RANK_HEADER_HEIGHT + RANK_MAX_ROWS * RANK_ROW_HEIGHT + RANK_FOOTER_HEIGHT
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return canvas
  const scale = snapshot.width > 0 ? RANK_FRAME_WIDTH / snapshot.width : 1

  ctx.fillStyle = resolveCssColor('var(--color-surface)')
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  // 标题行：标题 · 年份（GIF 离开页面后仍能看出是哪一年）
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = resolveCssColor('var(--color-text-strong)')
  ctx.font = `600 15px ${FONT_STACK}`
  ctx.fillText(`${snapshot.title} · ${snapshot.year}`, RANK_SIDE_PADDING, RANK_HEADER_HEIGHT / 2)
  ctx.font = `11px ${FONT_STACK}`
  ctx.fillStyle = resolveCssColor('var(--color-text-subtle)')
  ctx.textAlign = 'right'
  ctx.fillText('单位：篇', canvas.width - RANK_SIDE_PADDING, RANK_HEADER_HEIGHT / 2)

  const primary = resolveCssColor('var(--color-primary)')
  const trackColor = resolveCssColor('var(--color-neutral-bg)')
  const trackWidth = canvas.width - RANK_LABEL_X - RANK_SIDE_PADDING

  snapshot.rows.slice(0, RANK_MAX_ROWS).forEach((row, index) => {
    // 行位用 DOM 的实时偏移量：FLIP 过渡中的排名变化也能被记录
    const rowTop = RANK_HEADER_HEIGHT + row.offsetY * scale
    const rowHeight = Math.min(row.height * scale, RANK_ROW_HEIGHT * 1.5)
    const textY = rowTop + rowHeight * 0.32
    const barY = rowTop + rowHeight * 0.62

    ctx.textAlign = 'left'
    ctx.font = `700 14px ${FONT_STACK}`
    ctx.fillStyle = index < 3 ? primary : resolveCssColor('var(--color-text-faint)')
    ctx.fillText(String(index + 1), RANK_SIDE_PADDING, textY)

    ctx.font = `500 14px ${FONT_STACK}`
    ctx.fillStyle = resolveCssColor('var(--color-text)')
    drawClippedText(ctx, row.label, RANK_LABEL_X, textY, trackWidth - 90)

    ctx.textAlign = 'right'
    ctx.font = `600 14px ${FONT_STACK}`
    ctx.fillStyle = resolveCssColor('var(--color-text-strong)')
    ctx.fillText(row.countText, canvas.width - RANK_SIDE_PADDING, textY)

    ctx.beginPath()
    ctx.roundRect(RANK_LABEL_X, barY, trackWidth, RANK_BAR_HEIGHT, RANK_BAR_HEIGHT / 2)
    ctx.fillStyle = trackColor
    ctx.fill()

    const barWidth = Math.max(4, trackWidth * row.barRatio)
    ctx.beginPath()
    ctx.roundRect(RANK_LABEL_X, barY, barWidth, RANK_BAR_HEIGHT, RANK_BAR_HEIGHT / 2)
    ctx.fillStyle = row.color
    ctx.fill()
  })

  // 口径行：与页面一致，说明分母与记录数
  const footerTop = canvas.height - RANK_FOOTER_HEIGHT
  ctx.fillStyle = resolveCssColor('var(--color-surface-muted)')
  ctx.fillRect(0, footerTop, canvas.width, RANK_FOOTER_HEIGHT)
  ctx.strokeStyle = resolveCssColor('var(--color-border)')
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(0, footerTop + 0.5)
  ctx.lineTo(canvas.width, footerTop + 0.5)
  ctx.stroke()
  ctx.textAlign = 'left'
  ctx.font = `11px ${FONT_STACK}`
  ctx.fillStyle = resolveCssColor('var(--color-text-subtle)')
  ctx.fillText(snapshot.footer, RANK_SIDE_PADDING, footerTop + RANK_FOOTER_HEIGHT / 2)

  return canvas
}
