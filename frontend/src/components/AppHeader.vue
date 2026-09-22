<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'

interface NavItem {
  label: string
  to: string
  match: string[]
}

const navItems: NavItem[] = [
  { label: '热门方向', to: '/', match: ['/'] },
  { label: '热度走势', to: '/trends', match: ['/trends'] },
  { label: '论文管理', to: '/papers', match: ['/papers'] },
  { label: '采集与导入', to: '/collect', match: ['/collect'] },
  { label: '关于平台', to: '/about', match: ['/about'] },
]

const route = useRoute()

function isActive(item: NavItem): boolean {
  if (item.to === '/') return route.path === '/'
  return item.match.some((prefix) => route.path.startsWith(prefix))
}
</script>

<template>
  <header class="site-header">
    <div class="layout-container header-inner">
      <RouterLink class="brand" to="/">
        <span class="brand-mark" aria-hidden="true">CV</span>
        <span class="brand-text">
          <span class="brand-name">CVPlatform</span>
          <span class="brand-sub">计算机视觉顶会热词分析</span>
        </span>
      </RouterLink>

      <nav class="site-nav" aria-label="主导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          class="nav-link"
          :class="{ 'is-active': isActive(item) }"
          :to="item.to"
          :aria-current="isActive(item) ? 'page' : undefined"
        >
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="header-meta">
        <span class="badge badge-warn">演示数据</span>
        <span class="header-scope">尚未接入后端接口</span>
      </div>
    </div>
  </header>
</template>

<style scoped>
.site-header {
  position: sticky;
  top: 0;
  z-index: 30;
  border-bottom: 1px solid var(--color-border);
  background: rgb(255 255 255 / 95%);
  backdrop-filter: blur(8px);
}

.header-inner {
  display: flex;
  align-items: center;
  gap: 32px;
  height: var(--header-height);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-strong);
}

.brand-sub {
  font-size: 11px;
  color: var(--color-text-subtle);
}

.site-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
}

.nav-link {
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  color: var(--color-text-subtle);
}

.nav-link:hover {
  background: var(--color-neutral-bg);
  color: var(--color-text-strong);
}

.nav-link.is-active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.header-scope {
  font-size: 12px;
  color: var(--color-text-subtle);
}

/* 窄窗口：品牌副标题与右侧说明先隐藏，主导航可横向滚动 */
@media (max-width: 1100px) {
  .header-scope {
    display: none;
  }
}

@media (max-width: 900px) {
  .header-inner {
    gap: 16px;
  }

  .brand-text {
    display: none;
  }

  .site-nav {
    overflow-x: auto;
    white-space: nowrap;
  }

  .nav-link {
    padding: 8px 10px;
  }
}
</style>
