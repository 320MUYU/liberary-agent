import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', component: () => import('@/views/DashboardView.vue'), meta: { title: '工作台' } },
    { path: '/labs', component: () => import('@/views/LabsView.vue'), meta: { title: '实验室资源' } },
    { path: '/reservations', component: () => import('@/views/ReservationsView.vue'), meta: { title: '我的预约' } },
    { path: '/assistant', component: () => import('@/views/AssistantView.vue'), meta: { title: 'AI 智能助理' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

export default router
