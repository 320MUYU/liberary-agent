<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import BookingDialog from '@/components/BookingDialog.vue'
import { useAuthStore } from '@/store/authStore'
import { bookings, labIcon, labStyle, labs, loadBookings, loadLabs, statusMap } from '@/store/labStore'

const router = useRouter()
const { userInfo } = useAuthStore()
const bookingOpen = ref(false)
// 实验室是进页面后异步取回来的，首屏这一刻 labs 还是空的，
// 所以默认选中项先给 null，等接口回来再补上
const selectedLab = ref(null)
const today = new Date()
const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
const upcoming = computed(() => bookings.filter((item) => ['approved', 'pending'].includes(item.status) && item.date >= todayKey).sort((a, b) => `${a.date}${a.start}`.localeCompare(`${b.date}${b.start}`)).slice(0, 3))
const approvedCount = computed(() => bookings.filter((item) => item.status === 'approved').length)
const monthlyCount = computed(() => bookings.filter((item) => item.date?.startsWith(todayKey.slice(0, 7))).length)
const approvedHours = computed(() => bookings.filter((item) => item.status === 'approved').reduce((hours, item) => {
  const [startHour, startMinute] = item.start.split(':').map(Number)
  const [endHour, endMinute] = item.end.split(':').map(Number)
  return hours + (endHour * 60 + endMinute - startHour * 60 - startMinute) / 60
}, 0))
const nextApproved = computed(() => upcoming.value.find((item) => item.status === 'approved'))
const welcomeMessage = computed(() => nextApproved.value
  ? `今天是 ${today.getMonth() + 1} 月 ${today.getDate()} 日，下一场已通过的实验安排在 ${nextApproved.value.date} ${nextApproved.value.start}。`
  : `今天是 ${today.getMonth() + 1} 月 ${today.getDate()} 日，可在“我的预约”查看申请与审核结果。`)
const userName = computed(() => userInfo.value?.name || userInfo.value?.username || '同学')

function openBooking(lab) { selectedLab.value = lab || labs[0] || null; bookingOpen.value = true }

onMounted(async () => {
  loadBookings(true).catch(() => {})
  try {
    await loadLabs()
    if (!selectedLab.value) selectedLab.value = labs[0] || null
  } catch {
    // 错误提示由请求拦截器统一处理
  }
})
function displayDate(date) { const [, month, day] = date.split('-'); return `${Number(month)}月${Number(day)}日` }
</script>

<template>
  <div class="dashboard">
    <section class="welcome-card">
      <div class="welcome-copy">
        <span class="eyebrow"><i></i> 2026 秋季学期</span>
        <h2>上午好，{{ userName }}</h2>
        <p>{{ welcomeMessage }}</p>
        <div class="welcome-actions">
          <el-button type="primary" size="large" @click="openBooking()"><el-icon><Plus /></el-icon>预约实验室</el-button>
          <button @click="router.push('/assistant')"><el-icon><MagicStick /></el-icon>让 AI 帮我选择</button>
        </div>
      </div>
      <div class="hero-visual" aria-hidden="true">
        <div class="orbit orbit-one"></div><div class="orbit orbit-two"></div>
        <div class="flask"><span class="flask-neck"></span><span class="flask-body"><i></i><i></i><i></i></span></div>
        <span class="atom atom-one">✦</span><span class="atom atom-two">＋</span>
      </div>
    </section>

    <section class="stats-grid">
      <article class="stat-card surface"><span class="stat-icon green"><el-icon><School /></el-icon></span><div><small>开放实验室</small><strong>{{ labs.filter(l => l.status !== 'maintenance').length }}<em>/ {{ labs.length }} 间</em></strong></div><span class="trend">实时</span></article>
      <article class="stat-card surface"><span class="stat-icon orange"><el-icon><Calendar /></el-icon></span><div><small>本月预约</small><strong>{{ monthlyCount }}<em>次</em></strong></div></article>
      <article class="stat-card surface"><span class="stat-icon blue"><el-icon><CircleCheck /></el-icon></span><div><small>已通过</small><strong>{{ approvedCount }}<em>项</em></strong></div><span class="trend">良好</span></article>
      <article class="stat-card surface"><span class="stat-icon purple"><el-icon><Timer /></el-icon></span><div><small>已通过时长</small><strong>{{ approvedHours }}<em>小时</em></strong></div></article>
    </section>

    <div class="content-grid">
      <section>
        <div class="section-heading"><div><h2>近期预约</h2><p>关注即将开始的实验安排</p></div><button class="text-action" @click="router.push('/reservations')">查看全部 <el-icon><Right /></el-icon></button></div>
        <div class="booking-list surface">
          <article v-for="item in upcoming" :key="item.id" class="booking-row">
            <div class="date-block"><strong>{{ item.date.slice(-2) }}</strong><span>{{ displayDate(item.date).slice(0, 2) }}</span></div>
            <div class="booking-info"><div><strong>{{ item.lab }}</strong><span :class="['status', statusMap[item.status].class]">{{ statusMap[item.status].label }}</span></div><p><el-icon><Location /></el-icon>{{ item.room }}<span></span><el-icon><Clock /></el-icon>{{ item.start }} — {{ item.end }}<span></span><el-icon><User /></el-icon>{{ item.people }} 人</p></div>
            <button class="more-button"><el-icon><MoreFilled /></el-icon></button>
          </article>
          <div v-if="!upcoming.length" class="empty-mini">暂无近期预约</div>
        </div>
      </section>

      <section>
        <div class="section-heading"><div><h2>本周使用情况</h2><p>你的实验时间分布</p></div><span class="week-label">09.21 — 09.27</span></div>
        <div class="weekly-card surface">
          <div class="chart-head"><div><strong>4.5</strong><span>小时</span><small>本周累计</small></div><span><i></i> 实验时长</span></div>
          <div class="bar-chart">
            <div v-for="(height, index) in [18, 58, 28, 78, 44, 8, 8]" :key="index" class="bar-column"><div class="bar-track"><i :style="{ height: `${height}%` }"></i></div><span>{{ ['一','二','三','四','五','六','日'][index] }}</span></div>
          </div>
        </div>
      </section>
    </div>

    <section class="recommendations">
      <div class="section-heading"><div><h2>为你推荐</h2><p>依据你的专业与历史预约智能匹配</p></div><button class="text-action" @click="router.push('/labs')">浏览全部实验室 <el-icon><Right /></el-icon></button></div>
      <div class="recommend-grid">
        <article v-for="lab in labs.slice(0, 3)" :key="lab.id" class="recommend-card surface">
          <div class="lab-illustration" :style="{ background: labStyle(lab.category).color, color: labStyle(lab.category).accent }"><el-icon><component :is="labIcon(lab.category)" /></el-icon><span>{{ lab.category }}</span></div>
          <div class="recommend-body"><div class="lab-title"><strong>{{ lab.name }}</strong><el-tag v-if="lab.status === 'available'" type="success" effect="light" size="small">可预约</el-tag><el-tag v-else type="warning" effect="light" size="small">{{ lab.status === 'maintenance' ? '维护中' : '使用中' }}</el-tag></div><p><el-icon><Location /></el-icon>{{ lab.building }} · {{ lab.code }}<span></span><el-icon><User /></el-icon>{{ lab.capacity }} 人</p><div class="equipment"><span v-for="item in lab.equipments.slice(0, 2)" :key="item.id">{{ item.name }}</span></div><button :disabled="lab.status !== 'available'" @click="openBooking(lab)">{{ lab.status === 'available' ? '立即预约' : '暂不可约' }}<el-icon><Right /></el-icon></button></div>
        </article>
      </div>
    </section>

    <BookingDialog v-model="bookingOpen" :selected-lab="selectedLab" />
  </div>
</template>

<style scoped>
.welcome-card { min-height: 218px; display: flex; justify-content: space-between; position: relative; overflow: hidden; margin-bottom: 20px; padding: 34px 40px; color: white; background: #1d5552; border-radius: 18px; box-shadow: 0 14px 34px rgba(25, 72, 69, .12); }.welcome-card::after { content: ''; position: absolute; inset: 0; background: linear-gradient(100deg, transparent 50%, rgba(126,215,185,.08)); pointer-events: none; }.welcome-copy { position: relative; z-index: 2; }.eyebrow { display: flex; align-items: center; gap: 7px; color: #abd0c8; font-size: 10px; font-weight: 700; letter-spacing: 1px; }.eyebrow i { width: 6px; height: 6px; background: var(--mint); border-radius: 50%; }.welcome-copy h2 { margin-top: 17px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 29px; font-weight: 600; }.welcome-copy > p { margin-top: 8px; color: #b6cdca; font-size: 12px; }.welcome-actions { display: flex; align-items: center; gap: 20px; margin-top: 25px; }.welcome-actions .el-button { --el-button-bg-color: #7ed7b9; --el-button-border-color: #7ed7b9; --el-button-text-color: #143736; --el-button-hover-bg-color: #91e0c5; --el-button-hover-border-color: #91e0c5; padding: 0 18px; }.welcome-actions > button { display: flex; align-items: center; gap: 6px; padding: 0; color: #d0e3df; font-size: 11px; font-weight: 700; background: none; border: 0; }
.hero-visual { width: 330px; position: absolute; right: 10px; top: 0; bottom: 0; }.orbit { position: absolute; border: 1px solid rgba(167, 226, 207, .18); border-radius: 50%; }.orbit-one { width: 230px; height: 230px; right: 27px; top: -6px; }.orbit-two { width: 145px; height: 145px; right: 70px; top: 37px; }.flask { position: absolute; right: 108px; top: 45px; width: 75px; height: 115px; }.flask-neck { display: block; width: 26px; height: 40px; margin: auto; border: 4px solid #8ad9bd; border-width: 0 4px; }.flask-body { width: 75px; height: 74px; display: block; position: relative; overflow: hidden; margin-top: -2px; background: rgba(126,215,185,.14); border: 4px solid #8ad9bd; border-radius: 17px 17px 28px 28px; }.flask-body::before { content: ''; position: absolute; left: -8px; right: -8px; bottom: -4px; height: 43px; background: #63c8a7; border-radius: 50% 50% 0 0; opacity: .78; }.flask-body i { position: absolute; z-index: 1; width: 6px; height: 6px; background: #d7f3e9; border-radius: 50%; }.flask-body i:nth-child(1) { bottom: 15px; left: 18px; }.flask-body i:nth-child(2) { bottom: 28px; left: 43px; }.flask-body i:nth-child(3) { bottom: 8px; left: 49px; }.atom { position: absolute; color: #7ed7b9; }.atom-one { top: 45px; right: 46px; font-size: 18px; }.atom-two { bottom: 40px; left: 35px; font-size: 20px; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 31px; }.stat-card { min-height: 91px; display: flex; align-items: center; gap: 13px; padding: 17px; }.stat-icon { width: 42px; height: 42px; display: grid; place-items: center; flex: none; font-size: 19px; border-radius: 11px; }.stat-icon.green { color: #287b70; background: #e1f1ec; }.stat-icon.orange { color: #aa6b2b; background: #faecdc; }.stat-icon.blue { color: #526f9c; background: #e7edf6; }.stat-icon.purple { color: #806495; background: #eee8f2; }.stat-card small { display: block; color: #889692; font-size: 9px; }.stat-card strong { display: block; margin-top: 2px; color: var(--ink); font-family: Georgia, serif; font-size: 23px; }.stat-card strong em { margin-left: 4px; color: #81918e; font-family: inherit; font-size: 10px; font-style: normal; font-weight: 500; }.trend { margin-left: auto; align-self: start; padding: 3px 6px; color: #76908c; font-size: 8px; background: #f4f6f3; border-radius: 5px; }.trend.up { color: #3e8878; background: #edf7f3; }
.content-grid { display: grid; grid-template-columns: 1.65fr 1fr; gap: 23px; margin-bottom: 32px; }.booking-list { overflow: hidden; }.booking-row { min-height: 83px; display: flex; align-items: center; gap: 15px; padding: 13px 17px; border-bottom: 1px solid #efeee9; }.booking-row:last-child { border: 0; }.date-block { width: 47px; height: 52px; display: flex; flex-direction: column; align-items: center; justify-content: center; flex: none; background: #edf5f2; border-radius: 9px; }.date-block strong { color: var(--mint-dark); font-family: Georgia, serif; font-size: 19px; line-height: 1; }.date-block span { margin-top: 4px; color: #75918c; font-size: 8px; }.booking-info { flex: 1; min-width: 0; }.booking-info > div { display: flex; align-items: center; gap: 12px; }.booking-info strong { overflow: hidden; color: #294846; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.booking-info p { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; margin-top: 7px; color: #84918f; font-size: 9px; }.booking-info p span { width: 1px; height: 10px; margin: 0 4px; background: #dfe3de; }.more-button { padding: 4px; color: #92a09d; background: none; border: 0; }.empty-mini { padding: 40px; color: #93a09d; text-align: center; }.week-label { color: #8a9996; font-size: 9px; }
.weekly-card { min-height: 251px; padding: 20px 22px 15px; }.chart-head { display: flex; justify-content: space-between; align-items: start; }.chart-head strong { color: var(--ink); font-family: Georgia, serif; font-size: 28px; }.chart-head div > span { margin-left: 3px; color: #6d817e; font-size: 9px; }.chart-head small { display: block; margin-top: -2px; color: #a1aaa8; font-size: 8px; }.chart-head > span { display: flex; align-items: center; gap: 5px; color: #879693; font-size: 8px; }.chart-head > span i { width: 7px; height: 7px; background: #69bea4; border-radius: 2px; }.bar-chart { height: 145px; display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; padding-top: 15px; }.bar-column { height: 100%; flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; }.bar-track { width: 100%; max-width: 21px; flex: 1; display: flex; align-items: end; background-image: linear-gradient(#eef0eb 1px, transparent 1px); background-size: 100% 33%; }.bar-track i { width: 100%; min-height: 4px; display: block; background: linear-gradient(to top, #4fa88e, #8dd5bc); border-radius: 5px 5px 2px 2px; }.bar-column span { color: #8b9997; font-size: 8px; }
.recommend-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 17px; }.recommend-card { overflow: hidden; transition: transform .2s, box-shadow .2s; }.recommend-card:hover { transform: translateY(-3px); box-shadow: 0 12px 26px rgba(31,68,66,.08); }.lab-illustration { height: 104px; display: flex; align-items: center; justify-content: center; position: relative; overflow: hidden; }.lab-illustration::before, .lab-illustration::after { content: ''; position: absolute; width: 90px; height: 90px; border: 1px solid currentColor; border-radius: 50%; opacity: .12; }.lab-illustration::before { left: -30px; top: -35px; }.lab-illustration::after { right: -25px; bottom: -45px; }.lab-illustration .el-icon { font-size: 37px; opacity: .78; }.lab-illustration > span { position: absolute; left: 13px; top: 12px; padding: 3px 7px; font-size: 8px; font-weight: 700; background: rgba(255,255,255,.55); border-radius: 5px; }.recommend-body { padding: 16px; }.lab-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.lab-title > strong { color: #284745; font-size: 12px; }.recommend-body > p { display: flex; align-items: center; gap: 4px; margin-top: 8px; color: #84918f; font-size: 8px; }.recommend-body > p span { width: 1px; height: 9px; margin: 0 3px; background: #dfe2dd; }.equipment { display: flex; gap: 5px; margin-top: 11px; }.equipment span { padding: 3px 7px; color: #667d79; font-size: 8px; background: #f2f5f1; border-radius: 5px; }.recommend-body > button { width: 100%; display: flex; align-items: center; justify-content: center; gap: 4px; margin-top: 14px; padding: 8px; color: #246d64; font-size: 9px; font-weight: 700; background: #edf7f3; border: 0; border-radius: 7px; }.recommend-body > button:disabled { color: #8b9593; background: #f1f2ef; cursor: not-allowed; }
@media (max-width: 1200px) { .stats-grid { grid-template-columns: repeat(2, 1fr); }.content-grid { grid-template-columns: 1fr; }.recommend-grid { grid-template-columns: repeat(2, 1fr); }.recommend-card:last-child { display: none; } }
@media (max-width: 700px) { .welcome-card { padding: 28px 24px; }.welcome-copy h2 { font-size: 25px; }.welcome-copy > p { max-width: 75%; line-height: 1.7; }.hero-visual { right: -115px; opacity: .5; }.stats-grid { grid-template-columns: 1fr 1fr; gap: 9px; }.stat-card { padding: 13px; }.stat-icon { width: 36px; height: 36px; }.trend { display: none; }.recommend-grid { grid-template-columns: 1fr; }.recommend-card:last-child { display: block; } }
@media (max-width: 450px) { .stats-grid { grid-template-columns: 1fr; }.welcome-actions { align-items: flex-start; flex-direction: column; gap: 13px; }.booking-row { padding: 12px; } }
</style>
