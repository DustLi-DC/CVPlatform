import { createRouter, createWebHistory } from 'vue-router'

import AboutView from '../views/AboutView.vue'
import CollectView from '../views/CollectView.vue'
import HomeView from '../views/HomeView.vue'
import PaperDetailView from '../views/PaperDetailView.vue'
import PapersView from '../views/PapersView.vue'
import TrendsView from '../views/TrendsView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { title: '热门方向总览' } },
    { path: '/trends', name: 'trends', component: TrendsView, meta: { title: '热度走势对比' } },
    { path: '/papers', name: 'papers', component: PapersView, meta: { title: '论文管理' } },
    {
      path: '/papers/:id(\\d+)',
      name: 'paper-detail',
      component: PaperDetailView,
      meta: { title: '论文详情' },
    },
    { path: '/collect', name: 'collect', component: CollectView, meta: { title: '采集与导入' } },
    { path: '/about', name: 'about', component: AboutView, meta: { title: '关于平台' } },
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
