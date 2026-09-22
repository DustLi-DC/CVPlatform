import { createRouter, createWebHistory } from 'vue-router'

import AboutView from '../views/AboutView.vue'
import CollectView from '../views/CollectView.vue'
import HomeView from '../views/HomeView.vue'
import PaperDetailView from '../views/PaperDetailView.vue'
import PapersView from '../views/PapersView.vue'
import TrendsView from '../views/TrendsView.vue'

/**
 * 页面数据来源。放在路由上而不是各页面里，保证页头提示与实际实现一致，
 * 接入接口时只需改这一处，不会出现"页面已接后端但提示仍写未接入"的漂移。
 * - api：数据来自后端接口
 * - demo：仍使用集中管理的演示数据（等待对应阶段的统计或采集接口）
 * - pending：页面结构就绪，但所需的接口尚未实现（如采集与导入）
 * - static：无数据，纯说明性内容
 */
export type DataSourceKind = 'api' | 'demo' | 'pending' | 'static'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
      meta: { title: '热门方向总览', dataSource: 'demo' satisfies DataSourceKind },
    },
    {
      path: '/trends',
      name: 'trends',
      component: TrendsView,
      meta: { title: '热度走势对比', dataSource: 'demo' satisfies DataSourceKind },
    },
    {
      path: '/papers',
      name: 'papers',
      component: PapersView,
      meta: { title: '论文管理', dataSource: 'api' satisfies DataSourceKind },
    },
    {
      path: '/papers/:id(\\d+)',
      name: 'paper-detail',
      component: PaperDetailView,
      meta: { title: '论文详情', dataSource: 'api' satisfies DataSourceKind },
    },
    {
      path: '/collect',
      name: 'collect',
      component: CollectView,
      meta: { title: '采集与导入', dataSource: 'pending' satisfies DataSourceKind },
    },
    {
      path: '/about',
      name: 'about',
      component: AboutView,
      meta: { title: '关于平台', dataSource: 'static' satisfies DataSourceKind },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior(_to, _from, savedPosition) {
    // 从详情返回列表时恢复原滚动位置，否则回到页首
    return savedPosition ?? { top: 0 }
  },
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · CVPlatform` : 'CVPlatform · 顶会论文分析平台'
})

export default router
