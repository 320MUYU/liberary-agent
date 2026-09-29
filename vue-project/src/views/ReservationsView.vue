<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import BookingDialog from '@/components/BookingDialog.vue'
import { bookings, cancelBooking, loadBookings, statusMap } from '@/store/labStore'

const activeStatus = ref('all')
const search = ref('')
const bookingOpen = ref(false)
const detail = ref(null)
const detailOpen = computed({ get: () => Boolean(detail.value), set: (open) => { if (!open) detail.value = null } })
const loading = ref(false)
const statusTabs = [{ value: 'all', label: '全部' }, { value: 'approved', label: '已通过' }, { value: 'pending', label: '审核中' }, { value: 'rejected', label: '未通过' }, { value: 'cancelled', label: '已取消' }]
const filtered = computed(() => bookings.filter((item) => (activeStatus.value === 'all' || item.status === activeStatus.value) && (!search.value || `${item.lab}${item.purpose}${item.room}`.toLowerCase().includes(search.value.toLowerCase()))))
const count = (status) => status === 'all' ? bookings.length : bookings.filter((item) => item.status === status).length

async function cancel(item) {
  try {
    await ElMessageBox.confirm(`确定取消 ${item.date} 的「${item.lab}」预约吗？`, '取消预约', { type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '保留预约' })
  } catch { return }
  try {
    await cancelBooking(item.id)
    ElMessage.success('预约已取消')
  } catch { /* 接口层已提示失败原因 */ }
}

onMounted(async () => {
  loading.value = true
  try { await loadBookings(true) } catch { /* 接口层已提示失败原因 */ }
  finally { loading.value = false }
})
</script>

<template>
  <div class="reservations-page">
    <div class="summary-grid">
      <article class="summary-card surface"><span class="summary-icon green"><el-icon><Calendar /></el-icon></span><div><small>全部预约</small><strong>{{ bookings.length }}</strong></div><p>条记录</p></article>
      <article class="summary-card surface"><span class="summary-icon orange"><el-icon><Loading /></el-icon></span><div><small>等待审核</small><strong>{{ count('pending') }}</strong></div><p>请耐心等待</p></article>
      <article class="summary-card surface"><span class="summary-icon blue"><el-icon><CircleCheck /></el-icon></span><div><small>审核通过</small><strong>{{ count('approved') }}</strong></div><p>按时到场</p></article>
      <article class="new-card" @click="bookingOpen = true"><span><el-icon><Plus /></el-icon></span><div><strong>新建预约</strong><p>选择实验室与时段</p></div><el-icon><Right /></el-icon></article>
    </div>

    <section v-loading="loading" class="records surface">
      <div class="records-head">
        <div><h2>预约记录</h2><p>管理和查看你的实验室申请</p></div>
        <el-input v-model="search" clearable placeholder="搜索实验室或用途" class="record-search"><template #prefix><el-icon><Search /></el-icon></template></el-input>
      </div>
      <div class="status-tabs">
        <button v-for="tab in statusTabs" :key="tab.value" :class="{ active: activeStatus === tab.value }" @click="activeStatus = tab.value">{{ tab.label }} <span>{{ count(tab.value) }}</span></button>
      </div>
      <div v-if="filtered.length" class="records-list">
        <article v-for="item in filtered" :key="item.id" class="record-row">
          <div class="date-card"><strong>{{ item.date.slice(-2) }}</strong><span>{{ Number(item.date.slice(5,7)) }}月</span></div>
          <div class="record-main"><div class="record-title"><h3>{{ item.lab }}</h3><span :class="['status', statusMap[item.status].class]">{{ statusMap[item.status].label }}</span></div><p class="purpose">{{ item.purpose }}</p><div class="record-meta"><span><el-icon><Location /></el-icon>{{ item.room }}</span><span><el-icon><Clock /></el-icon>{{ item.date }} · {{ item.start }} — {{ item.end }}</span><span><el-icon><User /></el-icon>{{ item.people }} 人</span></div></div>
          <div class="record-id"><small>预约编号</small><span>#{{ String(item.id).slice(-6) }}</span></div>
          <div class="record-actions"><el-button size="small" @click="detail = item">查看详情</el-button><el-button v-if="['approved','pending'].includes(item.status)" size="small" text type="danger" @click="cancel(item)">取消预约</el-button></div>
        </article>
      </div>
      <div v-else-if="!loading" class="records-empty"><span><el-icon><Calendar /></el-icon></span><h3>这里还没有预约记录</h3><p>调整筛选条件，或创建一条新的实验室预约</p><el-button type="primary" @click="bookingOpen = true">新建预约</el-button></div>
    </section>
    <BookingDialog v-model="bookingOpen" />
    <el-dialog v-model="detailOpen" title="预约详情" width="min(520px, 92vw)">
      <template v-if="detail">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="实验室">{{ detail.lab }} · {{ detail.room }}</el-descriptions-item>
          <el-descriptions-item label="预约时间">{{ detail.date }} {{ detail.start }} — {{ detail.end }}</el-descriptions-item>
          <el-descriptions-item label="实验人数">{{ detail.people }} 人</el-descriptions-item>
          <el-descriptions-item label="实验用途">{{ detail.purpose }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.note" label="补充说明">{{ detail.note }}</el-descriptions-item>
          <el-descriptions-item label="审核状态">{{ statusMap[detail.status]?.label || detail.status }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.reviewNote" label="审核意见">{{ detail.reviewNote }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 22px; }.summary-card { min-height: 94px; display: flex; align-items: center; gap: 13px; padding: 18px; }.summary-icon { width: 42px; height: 42px; display: grid; place-items: center; flex: none; font-size: 18px; border-radius: 11px; }.summary-icon.green { color: #287b70; background: #e2f2ed; }.summary-icon.orange { color: #aa6c2b; background: #f9eddf; }.summary-icon.blue { color: #5d72a1; background: #e8edf7; }.summary-card small { display: block; color: #8b9996; font-size: 9px; }.summary-card strong { display: block; color: var(--ink); font-family: Georgia, serif; font-size: 23px; }.summary-card > p { margin-left: auto; align-self: end; color: #9aa4a1; font-size: 8px; }.new-card { min-height: 94px; display: flex; align-items: center; gap: 12px; padding: 18px; color: white; background: #1d5552; border-radius: 15px; cursor: pointer; transition: transform .2s; }.new-card:hover { transform: translateY(-2px); }.new-card > span { width: 39px; height: 39px; display: grid; place-items: center; color: #173c3a; font-size: 19px; background: var(--mint); border-radius: 10px; }.new-card strong { font-size: 12px; }.new-card p { margin-top: 3px; color: #9ebfbb; font-size: 8px; }.new-card > .el-icon { margin-left: auto; color: #8eb6b1; }
.records { overflow: hidden; }.records-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 22px 24px 17px; }.records-head h2 { color: var(--ink); font-family: Georgia, 'Noto Serif SC', serif; font-size: 19px; }.records-head p { margin-top: 3px; color: #8b9996; font-size: 10px; }.record-search { width: 260px; }.status-tabs { display: flex; gap: 25px; padding: 0 24px; border-bottom: 1px solid #e8e9e3; }.status-tabs button { display: flex; align-items: center; gap: 6px; position: relative; padding: 0 0 13px; color: #81908d; font-size: 10px; font-weight: 600; background: none; border: 0; }.status-tabs button span { min-width: 18px; padding: 1px 5px; color: #7d8e8a; font-size: 8px; background: #f0f2ee; border-radius: 8px; }.status-tabs button.active { color: var(--mint-dark); }.status-tabs button.active::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--mint-dark); }.status-tabs button.active span { color: #246d64; background: #e6f3ef; }.record-row { min-height: 105px; display: flex; align-items: center; gap: 17px; padding: 17px 24px; border-bottom: 1px solid #eeeeea; }.record-row:last-child { border: 0; }.date-card { width: 51px; height: 58px; display: flex; flex-direction: column; align-items: center; justify-content: center; flex: none; background: #edf5f2; border-radius: 10px; }.date-card strong { color: var(--mint-dark); font-family: Georgia, serif; font-size: 20px; }.date-card span { color: #73908b; font-size: 8px; }.record-main { flex: 1; min-width: 0; }.record-title { display: flex; align-items: center; gap: 11px; }.record-title h3 { overflow: hidden; color: #294845; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.purpose { margin-top: 5px; color: #657b77; font-size: 10px; }.record-meta { display: flex; flex-wrap: wrap; gap: 13px; margin-top: 8px; }.record-meta span { display: flex; align-items: center; gap: 4px; color: #8b9895; font-size: 8px; }.record-id { width: 90px; padding-left: 18px; border-left: 1px solid #eceee9; }.record-id small, .record-id span { display: block; }.record-id small { color: #9aa5a2; font-size: 8px; }.record-id span { margin-top: 3px; color: #55706c; font-family: monospace; font-size: 10px; }.record-actions { width: 90px; display: flex; flex-direction: column; align-items: stretch; gap: 3px; }.records-empty { padding: 70px 20px; text-align: center; }.records-empty > span { width: 55px; height: 55px; display: grid; place-items: center; margin: auto; color: #78918d; font-size: 23px; background: #eef4f1; border-radius: 15px; }.records-empty h3 { margin-top: 14px; color: var(--ink); }.records-empty p { margin: 5px 0 17px; color: #8a9794; font-size: 10px; }
@media (max-width: 1050px) { .summary-grid { grid-template-columns: repeat(2, 1fr); } }.record-actions { width: auto; }
@media (max-width: 700px) { .summary-grid { grid-template-columns: 1fr 1fr; gap: 9px; }.summary-card, .new-card { padding: 13px; }.summary-card > p { display: none; }.records-head { align-items: stretch; flex-direction: column; }.record-search { width: 100%; }.status-tabs { gap: 17px; overflow-x: auto; }.status-tabs button { flex: none; }.record-row { align-items: flex-start; flex-wrap: wrap; padding: 15px; }.record-id { display: none; }.record-actions { width: 100%; flex-direction: row; padding-left: 68px; } }
@media (max-width: 430px) { .summary-grid { grid-template-columns: 1fr; }.summary-card, .new-card { min-height: 75px; }.record-meta span:nth-child(3) { display: none; } }
</style>
