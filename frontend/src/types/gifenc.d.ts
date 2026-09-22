/**
 * gifenc 没有随包提供类型声明，这里只声明本项目实际用到的三个 API。
 *
 * 刻意保持最小：用不到的重载、工具函数一律不声明，避免给人"类型很全"的错觉
 * （真正用到的就是 GIFEncoder / quantize / applyPalette）。
 */
declare module 'gifenc' {
  /** 一帧的写入参数：首帧带 palette + first 与 repeat 建立全局调色板与循环 */
  export interface GifFrameOptions {
    /** 调色板（quantize 的返回值），省略时沿用全局调色板 */
    palette?: number[][]
    /** 帧间隔（1/100 秒） */
    delay?: number
    /** 循环次数，0 表示无限循环；只在首帧生效 */
    repeat?: number
    /** 是否把本帧的调色板写成全局调色板（首帧传 true，后续帧共用，避免逐帧抖动与体积膨胀） */
    first?: boolean
    transparent?: boolean
    transparentIndex?: number
    dispose?: number
  }

  export interface GifEncoderInstance {
    writeFrame(index: Uint8Array, width: number, height: number, options?: GifFrameOptions): void
    finish(): void
    bytes(): Uint8Array
    bytesView(): Uint8Array
    reset(): void
  }

  export function GIFEncoder(): GifEncoderInstance

  /** 把 RGBA 像素量化成调色板（本项目固定 256 色 + rgb565，兼顾质量与速度） */
  export function quantize(
    rgba: Uint8Array | Uint8ClampedArray,
    maxColors: number,
    options?: { format?: 'rgb565' | 'rgb444' | 'rgba4444'; oneBitAlpha?: boolean | number },
  ): number[][]

  /** 把每个像素映射到调色板最近的颜色，得到 GIF 需要的索引位图 */
  export function applyPalette(
    rgba: Uint8Array | Uint8ClampedArray,
    palette: number[][],
    format?: 'rgb565' | 'rgb444' | 'rgba4444',
  ): Uint8Array
}
