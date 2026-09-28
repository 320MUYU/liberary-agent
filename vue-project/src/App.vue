<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getUserInfoApi } from '@/authApi'
import { notifications } from '@/store/labStore'
import { useAuthStore } from '@/store/authStore'

const route = useRoute()
const router = useRouter()
const mobileMenuOpen = ref(false)
const { token, userInfo, updateUser, logout } = useAuthStore()

const navigation = [
  { label: '工作台', path: '/', icon: 'Odometer' },
  { label: '实验室资源', path: '/labs', icon: 'School' },
  { label: '我的预约', path: '/reservations', icon: 'Calendar' },
  { label: 'AI 智能助理', path: '/assistant', icon: 'ChatDotRound', badge: 'AI' },
]

const currentTitle = computed(() => route.meta.title || '工作台')
const userName = computed(() => userInfo.value?.name || userInfo.value?.username || '用户')
const userAvatar = computed(() => userName.value.slice(0, 1))
const userRole = computed(() => ({ student: '学生', admin: '管理员' })[userInfo.value?.role] || '平台用户')
const userCaption = computed(() => `${userInfo.value?.username || '账号'} · ${userRole.value}`)

function navigate(path) {
  router.push(path)
  mobileMenuOpen.value = false
}

function handleProfileCommand(command) {
  if (command !== 'logout') return

  logout()
  router.replace('/login')
  ElMessage.success('已退出登录')
}

onMounted(async () => {
  if (!token.value) return

  try {
    updateUser(await getUserInfoApi())
  } catch {
    // 请求层会统一提示错误，并在登录失效时跳转登录页。
  }
})
</script>

<template>
  <router-view v-if="route.meta.layout === 'blank'" />

  <div v-else class="app-shell">
    <div v-if="mobileMenuOpen" class="mobile-mask" @click="mobileMenuOpen = false"></div>
    <aside class="sidebar" :class="{ 'is-open': mobileMenuOpen }">
      <button class="brand" aria-label="返回工作台" @click="navigate('/')">
        <span class="brand-mark"><span></span><span></span><span></span></span>
        <span>
          <strong>LabMind</strong>
          <small>智能实验室预约平台</small>
        </span>
      </button>

      <div class="nav-caption">学习与实验</div>
      <nav class="side-nav">
        <button
          v-for="item in navigation"
          :key="item.path"
          class="nav-item"
          :class="{ active: route.path === item.path }"
          @click="navigate(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <em v-if="item.badge">{{ item.badge }}</em>
        </button>
      </nav>

      <div class="sidebar-spacer"></div>
      <div class="ai-guide-card">
        <span class="sparkle"><el-icon><MagicStick /></el-icon></span>
        <strong>不知道选哪间？</strong>
        <p>告诉 AI 你的实验需求，它会分析设备与空闲时段。</p>
        <button @click="navigate('/assistant')">开始智能匹配 <el-icon><Right /></el-icon></button>
      </div>

      <div class="sidebar-footer">
        <button><el-icon><QuestionFilled /></el-icon> 使用帮助</button>
        <span>课程设计 · v1.0</span>
      </div>
    </aside>

    <section class="page-shell">
      <header class="topbar">
        <div class="topbar-left">
          <button class="menu-button" aria-label="打开菜单" @click="mobileMenuOpen = true"><el-icon><Menu /></el-icon></button>
          <div>
            <p class="crumb"><span>LabMind</span><el-icon><ArrowRight /></el-icon>{{ currentTitle }}</p>
            <h1>{{ currentTitle }}</h1>
          </div>
        </div>
        <div class="topbar-actions">
          <el-popover placement="bottom-end" :width="330" trigger="click" popper-class="notification-popover">
            <template #reference><button class="icon-button has-dot" aria-label="通知"><el-icon><Bell /></el-icon></button></template>
            <div class="notification-panel">
              <div class="notification-head"><strong>消息通知</strong><span>{{ notifications.length }} 条</span></div>
              <div v-for="item in notifications" :key="item.id" class="notification-item">
                <span :class="`notice-dot ${item.type}`"></span>
                <div><strong>{{ item.title }}</strong><p>{{ item.content }}</p><small>{{ item.time }}</small></div>
              </div>
            </div>
          </el-popover>
          <span class="top-divider"></span>
          <el-dropdown trigger="click" @command="handleProfileCommand">
            <button class="profile" type="button">
              <span class="avatar">{{ userAvatar }}</span>
              <div><strong>{{ userName }}</strong><small>{{ userCaption }}</small></div>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout"><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in"><component :is="Component" /></transition>
        </router-view>
      </main>
    </section>
  </div>
</template>

<style scoped>
.app-shell { min-height: 100vh; display: flex; background: var(--canvas); }
.sidebar { width: 256px; min-height: 100vh; padding: 28px 18px 22px; display: flex; flex-direction: column; position: fixed; inset: 0 auto 0 0; z-index: 30; color: #cad5de; background: #102b2c; box-shadow: 12px 0 38px rgba(15, 42, 43, .08); }
.brand { display: flex; align-items: center; gap: 12px; width: 100%; margin: 0 8px 42px; padding: 0; text-align: left; color: white; background: transparent; border: 0; }
.brand-mark { width: 39px; height: 39px; display: flex; align-items: end; justify-content: center; gap: 3px; padding: 9px; border-radius: 12px; background: var(--mint); transform: rotate(-2deg); }
.brand-mark span { display: block; width: 5px; border-radius: 5px 5px 2px 2px; background: #123334; }
.brand-mark span:nth-child(1) { height: 11px; }.brand-mark span:nth-child(2) { height: 20px; }.brand-mark span:nth-child(3) { height: 15px; }
.brand strong { display: block; font-family: Georgia, serif; font-size: 22px; letter-spacing: .3px; }.brand small { display: block; margin-top: 1px; color: #88a4a4; font-size: 10px; letter-spacing: .8px; }
.nav-caption { margin: 0 14px 10px; color: #607e7f; font-size: 10px; font-weight: 700; letter-spacing: 1.8px; }
.side-nav { display: flex; flex-direction: column; gap: 5px; }
.nav-item { position: relative; width: 100%; height: 48px; display: flex; align-items: center; gap: 13px; padding: 0 14px; color: #9bb0b1; background: transparent; border: 0; border-radius: 11px; transition: .2s ease; }
.nav-item .el-icon { font-size: 19px; }.nav-item span { font-size: 14px; font-weight: 600; }.nav-item em { margin-left: auto; padding: 1px 7px; color: #123334; font-size: 9px; font-style: normal; font-weight: 800; background: var(--mint); border-radius: 10px; }
.nav-item:hover { color: white; background: rgba(255, 255, 255, .055); }.nav-item.active { color: white; background: rgba(114, 208, 178, .13); }.nav-item.active::before { content: ''; position: absolute; left: -18px; width: 3px; height: 24px; border-radius: 0 4px 4px 0; background: var(--mint); }
.sidebar-spacer { flex: 1; }
.ai-guide-card { margin: 24px 3px 22px; padding: 20px 17px 17px; border: 1px solid rgba(126, 215, 185, .18); border-radius: 15px; background: linear-gradient(145deg, rgba(109, 204, 173, .11), rgba(255,255,255,.035)); }
.sparkle { width: 34px; height: 34px; display: grid; place-items: center; margin-bottom: 13px; color: #153536; background: var(--mint); border-radius: 10px; }.ai-guide-card strong { color: white; font-size: 13px; }.ai-guide-card p { margin: 7px 0 14px; color: #87a1a2; font-size: 11px; line-height: 1.65; }.ai-guide-card button { padding: 0; display: flex; align-items: center; gap: 6px; color: var(--mint); font-size: 11px; font-weight: 700; background: none; border: 0; }
.sidebar-footer { display: flex; align-items: center; justify-content: space-between; padding: 15px 7px 0; border-top: 1px solid rgba(255,255,255,.07); }.sidebar-footer button { display: flex; gap: 6px; padding: 0; color: #789394; font-size: 11px; background: none; border: 0; }.sidebar-footer span { color: #567576; font-size: 9px; }
.page-shell { width: calc(100% - 256px); min-height: 100vh; margin-left: 256px; }
.topbar { height: 86px; display: flex; align-items: center; justify-content: space-between; padding: 0 38px; position: sticky; top: 0; z-index: 20; background: rgba(248, 247, 243, .91); border-bottom: 1px solid #e8e6de; backdrop-filter: blur(15px); }
.topbar-left { display: flex; align-items: center; gap: 14px; }.crumb { display: flex; align-items: center; gap: 5px; margin-bottom: 4px; color: #91a09e; font-size: 10px; }.crumb span { color: #517271; }.crumb .el-icon { font-size: 9px; }.topbar h1 { color: var(--ink); font-family: Georgia, 'Noto Serif SC', serif; font-size: 23px; font-weight: 600; }
.topbar-actions { display: flex; align-items: center; gap: 17px; }.icon-button { width: 38px; height: 38px; display: grid; place-items: center; position: relative; color: #496361; font-size: 18px; background: #fff; border: 1px solid #e1e4dd; border-radius: 11px; }.has-dot::after { content: ''; position: absolute; top: 7px; right: 8px; width: 6px; height: 6px; background: var(--coral); border: 2px solid white; border-radius: 50%; }.top-divider { width: 1px; height: 30px; background: #dedfd9; }.profile { display: flex; align-items: center; gap: 10px; padding: 0; text-align: left; background: transparent; border: 0; }.avatar { width: 38px; height: 38px; display: grid; place-items: center; color: white; font-size: 13px; font-weight: 700; background: #2d6461; border-radius: 11px; }.profile strong, .profile small { display: block; }.profile strong { color: #203c3b; font-size: 12px; }.profile small { margin-top: 2px; color: #8b9997; font-size: 9px; }.profile > .el-icon { margin-left: 5px; color: #8b9997; font-size: 12px; }
.menu-button { display: none; width: 38px; height: 38px; background: white; border: 1px solid #e1e4dd; border-radius: 10px; }
.main-content { min-height: calc(100vh - 86px); padding: 30px 38px 42px; }
.mobile-mask { display: none; }
.notification-head { display: flex; justify-content: space-between; padding-bottom: 12px; border-bottom: 1px solid #edf0eb; }.notification-head span { color: #80908e; font-size: 11px; }.notification-item { display: flex; gap: 11px; padding: 14px 0; border-bottom: 1px solid #edf0eb; }.notification-item:last-child { border: 0; }.notice-dot { width: 8px; height: 8px; flex: none; margin-top: 5px; border-radius: 50%; background: #71c9aa; }.notice-dot.warning { background: #e8a65b; }.notification-item strong { color: #1e3b3a; font-size: 12px; }.notification-item p { margin: 3px 0; color: #6e7e7c; font-size: 11px; line-height: 1.5; }.notification-item small { color: #9da8a6; font-size: 9px; }
.page-enter-active, .page-leave-active { transition: opacity .15s ease, transform .15s ease; }.page-enter-from { opacity: 0; transform: translateY(5px); }.page-leave-to { opacity: 0; transform: translateY(-3px); }
@media (max-width: 900px) {
  .sidebar { transform: translateX(-105%); transition: transform .25s ease; }.sidebar.is-open { transform: translateX(0); }.mobile-mask { display: block; position: fixed; inset: 0; z-index: 29; background: rgba(9, 31, 32, .45); backdrop-filter: blur(2px); }.page-shell { width: 100%; margin-left: 0; }.menu-button { display: grid; place-items: center; }.topbar { padding: 0 20px; }.main-content { padding: 24px 20px 36px; }
}
@media (max-width: 600px) { .profile div, .profile > .el-icon, .top-divider { display: none; }.topbar { height: 74px; }.main-content { min-height: calc(100vh - 74px); padding: 20px 15px 30px; }.topbar h1 { font-size: 19px; }.crumb { display: none; } }
</style>
