import { createRouter, createWebHistory } from 'vue-router'
import { getToken, getUserInfo } from '../auth.js'

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
    { path: '/admin/users', component: () => import('@/views/admin/UserManageView.vue'), meta: { title: '用户管理', requiresAuth: true, requiresAdmin: true } },
    { path: '/admin/labs', component: () => import('@/views/admin/LabManageView.vue'), meta: { title: '实验室管理', requiresAuth: true, requiresAdmin: true } },
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

  // 管理页面只对管理员开放。这里判断的是本地缓存的用户信息，属于体验优化：
  // 本地缓存可以随便改，但后端每个管理接口都挂了 get_current_admin，
  // 伪装成管理员点进来也调不通任何接口。
  if (to.meta.requiresAdmin && getUserInfo()?.role !== 'admin') {
    return { path: '/' }
  }
})

export default router
