/**
 * 设计令牌（CSS 变量）→ 具体颜色值。
 *
 * canvas 不认识 `var(--x)`，任何要画到 canvas 上的颜色都必须先解析成 `#rrggbb`。
 * 单独放一个模块的原因：图表组件与 GIF 导出都要用它，但 GIF 导出不能因此
 * 把整个 ECharts（约 200 kB gzip）拉进来——只有解析颜色这一件事，不值得付那个代价。
 *
 * 解析失败时返回中性灰，不抛错：颜色拿不到不应让整张图或整个导出失败。
 */
export function resolveCssColor(color: string): string {
  if (!color.startsWith('var(')) return color
  const variable = color.slice(4, -1).trim()
  const value = getComputedStyle(document.documentElement).getPropertyValue(variable).trim()
  return value || '#94a3b8'
}
