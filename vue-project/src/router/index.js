import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../auth.js'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录', public: true, layout: 'blank' },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { title: '注册', public: true, layout: 'blank' },
    },
    { path: '/', component: () => import('@/views/DashboardView.vue'), meta: { title: '工作台', requiresAuth: true } },
    { path: '/labs', component: () => import('@/views/LabsView.vue'), meta: { title: '实验室资源', requiresAuth: true } },
    { path: '/reservations', component: () => import('@/views/ReservationsView.vue'), meta: { title: '我的预约', requiresAuth: true } },
    { path: '/assistant', component: () => import('@/views/AssistantView.vue'), meta: { title: 'AI 智能助理', requiresAuth: true } },
    { path: '/profile', component: () => import('@/views/ProfileView.vue'), meta: { title: '个人信息', requiresAuth: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const hasToken = Boolean(getToken())

  if (to.meta.requiresAuth && !hasToken) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  // 已登录用户不该再看到登录/注册页，直接送回工作台
  if (hasToken && (to.name === 'login' || to.name === 'register')) {
    return { path: '/' }
  }
})

export default router
