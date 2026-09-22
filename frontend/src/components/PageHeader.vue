<script setup lang="ts">
/**
 * 页面标题区。两种形态与原型一致：
 * hero：首页的深蓝渐变标题区，带统计小卡；
 * plain：其余页面的浅色标题区，右侧可放筛选图例或页面级操作。
 */
withDefaults(
  defineProps<{
    variant?: 'hero' | 'plain'
    eyebrow: string
    title: string
    description: string
    stats?: { label: string; value: string; hint: string }[]
    notice?: string
  }>(),
  { variant: 'plain', stats: () => [], notice: '' },
)
</script>

<template>
  <section v-if="variant === 'hero'" class="page-hero">
    <div class="hero-main">
      <p class="hero-eyebrow">{{ eyebrow }}</p>
      <h1 class="hero-title">{{ title }}</h1>
      <p class="hero-desc">{{ description }}</p>
      <p v-if="notice" class="hero-notice">{{ notice }}</p>
    </div>
    <div v-if="stats.length" class="hero-stats">
      <div v-for="item in stats" :key="item.label" class="hero-stat">
        <div class="hero-stat-label">{{ item.label }}</div>
        <div class="hero-stat-value">{{ item.value }}</div>
        <div class="hero-stat-hint">{{ item.hint }}</div>
      </div>
    </div>
  </section>

  <div v-else class="page-plain">
    <div class="plain-main">
      <p class="plain-eyebrow">{{ eyebrow }}</p>
      <h1 class="plain-title">{{ title }}</h1>
      <p class="plain-desc">{{ description }}</p>
    </div>
    <div v-if="$slots.aside" class="plain-aside">
      <slot name="aside" />
    </div>
  </div>
</template>

<style scoped>
.page-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 40px;
  margin-bottom: 24px;
  padding: 32px 36px;
  border-radius: var(--radius-xl);
  background: linear-gradient(
    90deg,
    var(--color-title-deep) 0%,
    var(--color-primary) 55%,
    var(--color-conf-cvpr) 100%
  );
  color: #fff;
}

.hero-main {
  max-width: 720px;
}

.hero-eyebrow {
  margin-bottom: 12px;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: #dbeafe;
}

.hero-title {
  margin-bottom: 12px;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.25;
}

.hero-desc {
  font-size: 15px;
  line-height: 1.75;
  color: #eff6ff;
}

.hero-notice {
  margin-top: 20px;
  font-size: 12px;
  color: #dbeafe;
}

.hero-stats {
  display: flex;
  gap: 12px;
  flex: 0 0 auto;
}

.hero-stat {
  width: 150px;
  padding: 12px 16px;
  border: 1px solid rgb(255 255 255 / 20%);
  border-radius: var(--radius-lg);
  background: rgb(255 255 255 / 10%);
}

.hero-stat-label,
.hero-stat-hint {
  font-size: 11px;
  color: #dbeafe;
}

.hero-stat-value {
  margin: 4px 0;
  font-size: 24px;
  font-weight: 700;
}

.page-plain {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.plain-main {
  min-width: 0;
}

.plain-eyebrow {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--color-text-subtle);
}

.plain-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text-strong);
}

.plain-desc {
  max-width: 860px;
  margin-top: 8px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.plain-aside {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
  flex-wrap: wrap;
}

/* 窄窗口：标题区纵向排列 */
@media (max-width: 1100px) {
  .page-hero {
    flex-direction: column;
    align-items: flex-start;
    gap: 24px;
    padding: 28px;
  }

  .hero-stats {
    flex-wrap: wrap;
  }

  .hero-title {
    font-size: 26px;
  }

  .page-plain {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
