<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getUserInfoApi } from '@/authApi'
import { BRAND } from '@/config/brand'
import { loadLabs, notifications } from '@/store/labStore'
import { useAuthStore } from '@/store/authStore'
import { resolveAssetUrl } from '@/utils/url.js'

const route = useRoute()
const router = useRouter()
const mobileMenuOpen = ref(false)
const { token, userInfo, updateUser, logout } = useAuthStore()

const navigation = [
  { label: '概览', path: '/', icon: 'House' },
  { label: '图书检索', path: '/books', icon: 'Collection' },
  { label: '我的借阅', path: '/loans', icon: 'Tickets' },
  { label: '学习空间', path: '/spaces', icon: 'Reading' },
  { label: '我的预约', path: '/reservations', icon: 'Calendar' },
  { label: '阅见 AI', path: '/assistant', icon: 'ChatDotRound', badge: 'AI' }
]

// 管理菜单只在管理员登录时出现。这只是"不给普通用户看"，不是权限控制：
// 真正的拦截在后端接口的 get_current_admin 上。
const adminNavigation = [
  { label: '书目与馆藏', path: '/admin/books', icon: 'Collection' },
  { label: '借还审核', path: '/admin/loans', icon: 'Tickets' },
  { label: '读者管理', path: '/admin/users', icon: 'UserFilled' },
  { label: '空间管理', path: '/admin/labs', icon: 'Reading' },
  { label: '设施管理', path: '/admin/equipments', icon: 'SetUp' },
  { label: '预约审核', path: '/admin/reservations', icon: 'Calendar' },
  { label: '知识库管理', path: '/admin/knowledge', icon: 'Document' },
  { label: 'AI 效果审核', path: '/admin/evaluation-reviews', icon: 'Checked' }
]
const isAdmin = computed(() => userInfo.value?.role === 'admin')

const currentTitle = computed(() => route.meta.title || '工作台')
const userName = computed(() => userInfo.value?.name || userInfo.value?.username || '用户')
const userAvatar = computed(() => userName.value.slice(0, 1))
const userRole = computed(
  () => ({ student: '读者', admin: '管理员' })[userInfo.value?.role] || '平台用户'
)
const userCaption = computed(() => `${userInfo.value?.username || '账号'} · ${userRole.value}`)

const userAvatarUrl = computed(() => resolveAssetUrl(userInfo.value?.avatar))

function navigate(path) {
  router.push(path)
  mobileMenuOpen.value = false
}

function handleProfileCommand(command) {
  if (command === 'profile') {
    router.push('/profile')
    return
  }

  if (command === 'logout') {
    logout()
    router.replace('/login')
    ElMessage.success('已退出登录')
  }
}

onMounted(async () => {
  if (!token.value) return

  // 实验室列表在这里统一拉一次：预约弹窗可以从工作台、实验室资源、
  // 我的预约、AI 助理四个入口打开，与其每个入口各拉一次，
  // 不如在应用外壳里拉一次（loadLabs 内部有去重，不会重复请求）
  loadLabs().catch(() => {})

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
        <span class="brand-mark"><span></span><span></span></span>
        <span>
          <strong>{{ BRAND.name }}</strong>
          <small>{{ BRAND.englishName }}</small>
        </span>
      </button>

      <div class="nav-caption">阅读与空间</div>
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

      <template v-if="isAdmin">
        <div class="nav-caption is-group">系统管理</div>
        <nav class="side-nav">
          <button
            v-for="item in adminNavigation"
            :key="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
            @click="navigate(item.path)"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </button>
        </nav>
      </template>

      <div class="sidebar-spacer"></div>
      <div class="ai-guide-card">
        <span class="sparkle"
          ><el-icon><MagicStick /></el-icon
        ></span>
        <strong>不知道选哪间？</strong>
        <p>告诉 AI 你的学习需求，快速了解适合的空间与预约规则。</p>
        <button @click="navigate('/assistant')">
          咨询空间助手 <el-icon><Right /></el-icon>
        </button>
      </div>

      <div class="sidebar-footer">
        <button>
          <el-icon><QuestionFilled /></el-icon> 使用帮助
        </button>
        <span>{{ BRAND.name }} · v1.0</span>
      </div>
    </aside>

    <section class="page-shell">
      <header class="topbar">
        <div class="topbar-left">
          <button class="menu-button" aria-label="打开菜单" @click="mobileMenuOpen = true">
            <el-icon><Menu /></el-icon>
          </button>
          <div>
            <p class="crumb">
              <span>{{ BRAND.name }}</span
              ><el-icon><ArrowRight /></el-icon>{{ currentTitle }}
            </p>
            <h1>{{ currentTitle }}</h1>
          </div>
        </div>
        <div class="topbar-actions">
          <el-popover
            placement="bottom-end"
            :width="330"
            trigger="click"
            popper-class="notification-popover"
          >
            <template #reference
              ><button
                class="icon-button"
                :class="{ 'has-dot': notifications.length > 0 }"
                aria-label="通知"
              >
                <el-icon><Bell /></el-icon></button
            ></template>
            <div class="notification-panel">
              <div class="notification-head">
                <strong>消息通知</strong><span>{{ notifications.length }} 条</span>
              </div>
              <div v-for="item in notifications" :key="item.id" class="notification-item">
                <span :class="`notice-dot ${item.type}`"></span>
                <div>
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.content }}</p>
                  <small>{{ item.time }}</small>
                </div>
              </div>
              <div v-if="!notifications.length" class="notification-empty">暂无通知</div>
            </div>
          </el-popover>
          <span class="top-divider"></span>
          <el-dropdown trigger="click" @command="handleProfileCommand">
            <button class="profile" type="button">
              <span class="avatar"
                ><img v-if="userAvatarUrl" :src="userAvatarUrl" alt="" /><template v-else>{{
                  userAvatar
                }}</template></span
              >
              <div>
                <strong>{{ userName }}</strong
                ><small>{{ userCaption }}</small>
              </div>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile"
                  ><el-icon><User /></el-icon>读者资料</el-dropdown-item
                >
                <el-dropdown-item command="logout"
                  ><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item
                >
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
.app-shell {
  min-height: 100vh;
  display: flex;
  background: var(--canvas);
}
.sidebar {
  width: 256px;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior-y: contain;
  padding: 28px 18px 22px;
  display: flex;
  flex-direction: column;
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 30;
  color: #cad5de;
  background: #102b2c;
  box-shadow: 12px 0 38px rgba(15, 42, 43, 0.08);
}
.sidebar > * {
  flex-shrink: 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  width: auto;
  margin: 0 8px 42px;
  padding: 0;
  text-align: left;
  color: white;
  background: transparent;
  border: 0;
}
.brand-mark {
  width: 39px;
  height: 39px;
  display: flex;
  align-items: end;
  justify-content: center;
  gap: 3px;
  padding: 9px;
  border-radius: 12px;
  background: var(--mint);
  transform: rotate(-2deg);
}
.brand-mark span {
  display: block;
  width: 5px;
  border-radius: 5px 5px 2px 2px;
  background: #123334;
}
.brand-mark span:nth-child(1) {
  height: 11px;
}
.brand-mark span:nth-child(2) {
  height: 20px;
}
.brand-mark span:nth-child(3) {
  height: 15px;
}
.brand strong {
  display: block;
  font-family: Georgia, serif;
  font-size: 22px;
  letter-spacing: 0.3px;
}
.brand small {
  display: block;
  margin-top: 1px;
  color: #88a4a4;
  font-size: 10px;
  letter-spacing: 0.8px;
}
.nav-caption {
  margin: 0 14px 10px;
  color: #607e7f;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.8px;
}
.nav-caption.is-group {
  margin-top: 26px;
}
.side-nav {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.nav-item {
  position: relative;
  width: 100%;
  height: 48px;
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 0 14px;
  color: #9bb0b1;
  background: transparent;
  border: 0;
  border-radius: 11px;
  transition: 0.2s ease;
}
.nav-item .el-icon {
  font-size: 19px;
}
.nav-item span {
  font-size: 14px;
  font-weight: 600;
}
.nav-item em {
  margin-left: auto;
  padding: 1px 7px;
  color: #123334;
  font-size: 9px;
  font-style: normal;
  font-weight: 800;
  background: var(--mint);
  border-radius: 10px;
}
.nav-item:hover {
  color: white;
  background: rgba(255, 255, 255, 0.055);
}
.nav-item.active {
  color: white;
  background: rgba(114, 208, 178, 0.13);
}
.nav-item.active::before {
  content: '';
  position: absolute;
  left: -18px;
  width: 3px;
  height: 24px;
  border-radius: 0 4px 4px 0;
  background: var(--mint);
}
.sidebar-spacer {
  flex: 1;
}
.ai-guide-card {
  margin: 24px 3px 22px;
  padding: 20px 17px 17px;
  border: 1px solid rgba(126, 215, 185, 0.18);
  border-radius: 15px;
  background: linear-gradient(145deg, rgba(109, 204, 173, 0.11), rgba(255, 255, 255, 0.035));
}
.sparkle {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  margin-bottom: 13px;
  color: #153536;
  background: var(--mint);
  border-radius: 10px;
}
.ai-guide-card strong {
  color: white;
  font-size: 13px;
}
.ai-guide-card p {
  margin: 7px 0 14px;
  color: #87a1a2;
  font-size: 11px;
  line-height: 1.65;
}
.ai-guide-card button {
  padding: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--mint);
  font-size: 11px;
  font-weight: 700;
  background: none;
  border: 0;
}
.sidebar-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 7px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
}
.sidebar-footer button {
  display: flex;
  gap: 6px;
  padding: 0;
  color: #789394;
  font-size: 11px;
  background: none;
  border: 0;
}
.sidebar-footer span {
  color: #567576;
  font-size: 9px;
}
.page-shell {
  width: calc(100% - 256px);
  min-height: 100vh;
  margin-left: 256px;
}
.topbar {
  height: 86px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 38px;
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(248, 247, 243, 0.91);
  border-bottom: 1px solid #e8e6de;
  backdrop-filter: blur(15px);
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.crumb {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 4px;
  color: #91a09e;
  font-size: 10px;
}
.crumb span {
  color: #517271;
}
.crumb .el-icon {
  font-size: 9px;
}
.topbar h1 {
  color: var(--ink);
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: 23px;
  font-weight: 600;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 17px;
}
.icon-button {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  position: relative;
  color: #496361;
  font-size: 18px;
  background: #fff;
  border: 1px solid #e1e4dd;
  border-radius: 11px;
}
.has-dot::after {
  content: '';
  position: absolute;
  top: 7px;
  right: 8px;
  width: 6px;
  height: 6px;
  background: var(--coral);
  border: 2px solid white;
  border-radius: 50%;
}
.top-divider {
  width: 1px;
  height: 30px;
  background: #dedfd9;
}
.profile {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0;
  text-align: left;
  background: transparent;
  border: 0;
}
.avatar {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  overflow: hidden;
  color: white;
  font-size: 13px;
  font-weight: 700;
  background: #2d6461;
  border-radius: 11px;
}
.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.profile strong,
.profile small {
  display: block;
}
.profile strong {
  color: #203c3b;
  font-size: 12px;
}
.profile small {
  margin-top: 2px;
  color: #8b9997;
  font-size: 9px;
}
.profile > .el-icon {
  margin-left: 5px;
  color: #8b9997;
  font-size: 12px;
}
.menu-button {
  display: none;
  width: 38px;
  height: 38px;
  background: white;
  border: 1px solid #e1e4dd;
  border-radius: 10px;
}
.main-content {
  min-height: calc(100vh - 86px);
  padding: 30px 38px 42px;
}
.mobile-mask {
  display: none;
}
.notification-head {
  display: flex;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid #edf0eb;
}
.notification-head span {
  color: #80908e;
  font-size: 11px;
}
.notification-item {
  display: flex;
  gap: 11px;
  padding: 14px 0;
  border-bottom: 1px solid #edf0eb;
}
.notification-item:last-child {
  border: 0;
}
.notice-dot {
  width: 8px;
  height: 8px;
  flex: none;
  margin-top: 5px;
  border-radius: 50%;
  background: #71c9aa;
}
.notice-dot.warning {
  background: #e8a65b;
}
.notification-item strong {
  color: #1e3b3a;
  font-size: 12px;
}
.notification-item p {
  margin: 3px 0;
  color: #6e7e7c;
  font-size: 11px;
  line-height: 1.5;
}
.notification-item small {
  color: #9da8a6;
  font-size: 9px;
}
.notification-empty {
  padding: 24px 0 8px;
  color: #80908e;
  font-size: 12px;
  text-align: center;
}
.page-enter-active,
.page-leave-active {
  transition:
    opacity 0.15s ease,
    transform 0.15s ease;
}
.page-enter-from {
  opacity: 0;
  transform: translateY(5px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}
@media (max-width: 900px) {
  .sidebar {
    transform: translateX(-105%);
    transition: transform 0.25s ease;
  }
  .sidebar.is-open {
    transform: translateX(0);
  }
  .mobile-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 29;
    background: rgba(9, 31, 32, 0.45);
    backdrop-filter: blur(2px);
  }
  .page-shell {
    width: 100%;
    margin-left: 0;
  }
  .menu-button {
    display: grid;
    place-items: center;
  }
  .topbar {
    padding: 0 20px;
  }
  .main-content {
    padding: 24px 20px 36px;
  }
}
@media (max-width: 600px) {
  .profile div,
  .profile > .el-icon,
  .top-divider {
    display: none;
  }
  .topbar {
    height: 74px;
  }
  .main-content {
    min-height: calc(100vh - 74px);
    padding: 20px 15px 30px;
  }
  .topbar h1 {
    font-size: 19px;
  }
  .crumb {
    display: none;
  }
}

/* 阅见应用外壳 */
.sidebar {
  color: var(--text);
  background: #fffefa;
  border-right: 1px solid var(--line);
  box-shadow: 10px 0 34px rgba(23, 50, 77, 0.05);
}
.brand {
  color: var(--ink);
}
.brand-mark {
  align-items: center;
  gap: 0;
  position: relative;
  padding: 9px 7px;
  background: var(--navy-900);
  transform: none;
}
.brand-mark span {
  width: 50%;
  height: 21px !important;
  background: #fffefa;
}
.brand-mark span:first-child {
  border-radius: 2px 0 7px 2px;
  transform: skewY(8deg);
}
.brand-mark span:last-child {
  border-radius: 0 2px 2px 7px;
  transform: skewY(-8deg);
}
.brand strong {
  color: var(--navy-900);
  font-family: 'Songti SC', SimSun, serif;
  font-size: 24px;
  letter-spacing: 3px;
}
.brand small {
  color: #8795a0;
  font-weight: 700;
  letter-spacing: 1.7px;
}
.nav-caption {
  color: #8c969c;
}
.nav-item {
  color: #566b7c;
}
.nav-item:hover {
  color: var(--navy-900);
  background: #f1eee6;
}
.nav-item.active {
  color: var(--navy-900);
  background: var(--gold-100);
}
.nav-item.active::before {
  background: var(--gold-600);
}
.nav-item em {
  color: #fff;
  background: var(--navy-900);
}
.ai-guide-card {
  border-color: #e0d1b6;
  background: linear-gradient(145deg, #f8f0e2, #fffdf8);
}
.sparkle {
  color: #fff;
  background: var(--navy-900);
}
.ai-guide-card strong {
  color: var(--ink);
}
.ai-guide-card p {
  color: #697987;
}
.ai-guide-card button {
  min-height: 44px;
  color: var(--gold-700);
}
.sidebar-footer {
  border-top-color: var(--line);
}
.sidebar-footer button,
.sidebar-footer span {
  color: #7a8994;
}
.topbar {
  background: rgba(246, 243, 236, 0.92);
  border-bottom-color: var(--line);
}
.crumb span {
  color: var(--gold-700);
}
.icon-button,
.menu-button {
  color: var(--navy-800);
  background: #fffefa;
  border-color: var(--line);
}
.avatar {
  background: var(--navy-900);
}
.profile strong {
  color: var(--ink);
}
@media (max-width: 900px) {
  .mobile-mask {
    background: rgba(16, 38, 58, 0.48);
  }
}
</style>
