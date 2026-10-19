<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getToken } from '@/auth'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cancelLoanApi, getMyLoanApi, getMyLoansApi, requestLoanReturnApi } from '@/loanApi.js'
import { formatLoanTime, loanActions, LOAN_STATUSES } from '@/utils/library.js'

const items = ref([])
const total = ref(0)
const page = ref(1)
const status = ref('')
const loading = ref(false)
const loadFailed = ref(false)
const busyKey = ref('')
const detail = ref(null)
const detailVisible = ref(false)
let sequence = 0
let detailSequence = 0
const route = useRoute()

async function openLinkedLoan() {
  const current = ++detailSequence
  detailVisible.value = false
  detail.value = null
  const raw = route.query.loan_id
  if (raw === undefined) return
  const id = Number(raw)
  if (!/^\d+$/.test(String(raw)) || !Number.isSafeInteger(id) || id < 1) {
    ElMessage.warning('借阅通知链接无效')
    return
  }
  const token = getToken()
  try {
    const loan = await getMyLoanApi(id)
    if (current !== detailSequence || getToken() !== token) return
    showDetail(loan)
  } catch {
    /* 接口会提示记录不存在或访问失败。 */
  }
}

watch(() => route.query.loan_id, openLinkedLoan)

async function fetchLoans() {
  const current = ++sequence
  loading.value = true
  loadFailed.value = false
  try {
    const data = await getMyLoansApi({
      page: page.value,
      page_size: 10,
      status: status.value || undefined
    })
    if (current !== sequence) return
    items.value = data.items
    total.value = data.total
    if (detail.value)
      detail.value = data.items.find((item) => item.id === detail.value.id) || detail.value
  } catch {
    if (current === sequence) loadFailed.value = true
  } finally {
    if (current === sequence) loading.value = false
  }
}

function changeStatus() {
  page.value = 1
  fetchLoans()
}
function showDetail(item) {
  detail.value = item
  detailVisible.value = true
}

async function act(item, action) {
  if (busyKey.value || !loanActions(item.status, 'reader').includes(action)) return
  busyKey.value = `${action}-${item.id}`
  const returning = action === 'request-return'
  try {
    try {
      await ElMessageBox.confirm(
        returning
          ? `已准备归还《${item.book_title}》？提交后请将实体书交给管理员，确认收到后才会结束借阅。`
          : `确定取消《${item.book_title}》的借阅申请吗？`,
        returning ? '申请归还' : '取消借阅申请',
        {
          confirmButtonText: returning ? '提交归还申请' : '确认取消',
          cancelButtonText: '返回',
          type: 'warning'
        }
      )
    } catch {
      return
    }
    if (returning) await requestLoanReturnApi(item.id)
    else await cancelLoanApi(item.id)
    ElMessage.success(returning ? '归还申请已提交，请等待管理员确认收到实体书' : '借阅申请已取消')
    detailVisible.value = false
    await fetchLoans()
  } catch {
    // 请求层已提示错误，仍可重试。
  } finally {
    busyKey.value = ''
  }
}

onMounted(() => {
  fetchLoans()
  openLinkedLoan()
})
onUnmounted(() => {
  sequence++
  detailSequence++
})
</script>

<template>
  <div class="loans-page">
    <section class="page-heading">
      <div>
        <span>MY BORROWING</span>
        <h2>我的借阅</h2>
        <p>从申请到归还，每一步进度都在这里。</p>
      </div>
      <router-link to="/books"><el-button type="primary">查找图书</el-button></router-link>
    </section>
    <el-alert
      title="借期 30 天，每人最多 5 册；归还申请需管理员确认后才结束借阅。"
      type="info"
      :closable="false"
      show-icon
    />
    <section class="surface records">
      <div class="toolbar">
        <h3>借阅记录</h3>
        <el-select v-model="status" aria-label="按借阅状态筛选" @change="changeStatus"
          ><el-option label="全部状态" value="" /><el-option
            v-for="(value, key) in LOAN_STATUSES"
            :key="key"
            :label="value.label"
            :value="key" /></el-select
        ><el-button :loading="loading" :disabled="Boolean(busyKey)" @click="fetchLoans"
          >刷新</el-button
        >
      </div>
      <el-alert
        v-if="loadFailed"
        title="借阅记录加载失败，请点击刷新重试。"
        type="error"
        :closable="false"
      />
      <div v-loading="loading" class="record-list">
        <article v-for="item in items" :key="item.id" class="record-row">
          <div class="record-main">
            <div class="record-title">
              <h3>{{ item.book_title }}</h3>
              <el-tag :type="LOAN_STATUSES[item.status]?.type || 'info'" size="small">{{
                LOAN_STATUSES[item.status]?.label || '状态未知'
              }}</el-tag
              ><el-tag v-if="item.is_overdue" type="danger" size="small">已逾期</el-tag>
            </div>
            <p>申请编号 #{{ item.id }} · {{ formatLoanTime(item.create_time) }}</p>
            <p v-if="item.barcode">
              馆藏条码 {{ item.barcode }} · {{ item.location || '位置未提供' }}
            </p>
            <p v-if="item.due_at" :class="{ overdue: item.is_overdue }">
              应还时间：{{ formatLoanTime(item.due_at) }}
            </p>
            <p v-if="item.reject_reason" class="reason">拒绝原因：{{ item.reject_reason }}</p>
            <p v-if="item.status === 'return_pending'">
              等待管理员确认收到实体书，期间仍计入借阅册数。
            </p>
          </div>
          <div class="record-actions">
            <el-button size="small" @click="showDetail(item)">详情</el-button
            ><el-button
              v-if="loanActions(item.status, 'reader').includes('cancel')"
              size="small"
              type="danger"
              plain
              :disabled="Boolean(busyKey)"
              :loading="busyKey === `cancel-${item.id}`"
              @click="act(item, 'cancel')"
              >取消申请</el-button
            ><el-button
              v-if="loanActions(item.status, 'reader').includes('request-return')"
              size="small"
              type="primary"
              :disabled="Boolean(busyKey)"
              :loading="busyKey === `request-return-${item.id}`"
              @click="act(item, 'request-return')"
              >申请归还</el-button
            >
          </div>
        </article>
        <el-empty
          v-if="!items.length && !loading && !loadFailed"
          description="暂无符合条件的借阅记录"
          ><router-link to="/books"
            ><el-button type="primary">去查找图书</el-button></router-link
          ></el-empty
        >
      </div>
      <div class="pagination">
        <span>共 {{ total }} 条记录</span
        ><el-pagination
          v-model:current-page="page"
          :page-size="10"
          :total="total"
          layout="prev, pager, next"
          :disabled="loading"
          @current-change="fetchLoans"
        />
      </div>
    </section>
    <el-dialog v-model="detailVisible" title="借阅详情" width="min(620px, 94vw)">
      <el-descriptions v-if="detail" :column="1" border
        ><el-descriptions-item label="图书">{{ detail.book_title }}</el-descriptions-item
        ><el-descriptions-item label="状态">{{
          LOAN_STATUSES[detail.status]?.label || '状态未知'
        }}</el-descriptions-item
        ><el-descriptions-item label="申请时间">{{
          formatLoanTime(detail.create_time)
        }}</el-descriptions-item
        ><el-descriptions-item label="馆藏条码">{{
          detail.barcode || '待分配'
        }}</el-descriptions-item
        ><el-descriptions-item label="馆藏位置">{{
          detail.location || '待分配'
        }}</el-descriptions-item
        ><el-descriptions-item label="借出时间">{{
          formatLoanTime(detail.borrowed_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="应还时间">{{
          formatLoanTime(detail.due_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="归还申请">{{
          formatLoanTime(detail.return_requested_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="确认归还">{{
          formatLoanTime(detail.returned_at)
        }}</el-descriptions-item
        ><el-descriptions-item v-if="detail.reject_reason" label="拒绝原因">{{
          detail.reject_reason
        }}</el-descriptions-item></el-descriptions
      >
    </el-dialog>
  </div>
</template>

<style scoped>
.loans-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
}
.page-heading span {
  color: var(--mint-dark);
  font-size: 9px;
  letter-spacing: 1.5px;
}
.page-heading h2 {
  margin-top: 8px;
  font-size: 25px;
  color: var(--ink);
}
.page-heading p {
  margin-top: 7px;
  color: #889693;
  font-size: 12px;
}
.records {
  overflow: hidden;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px;
}
.toolbar h3 {
  margin-right: auto;
  font-size: 16px;
  color: var(--ink);
}
.toolbar .el-select {
  width: 160px;
}
.record-list {
  min-height: 250px;
}
.record-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 22px;
  border-top: 1px solid var(--line);
}
.record-main {
  min-width: 0;
}
.record-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.record-title h3 {
  font-size: 15px;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.record-main p {
  margin-top: 8px;
  font-size: 12px;
  color: #7a8994;
  overflow-wrap: anywhere;
}
.record-main .overdue,
.record-main .reason {
  color: #b54b42;
}
.record-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.record-actions .el-button + .el-button {
  margin: 0;
}
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 20px;
  border-top: 1px solid var(--line);
  color: #7a8994;
  font-size: 12px;
}
@media (max-width: 700px) {
  .toolbar {
    flex-wrap: wrap;
  }
  .toolbar h3 {
    width: 100%;
  }
  .record-row {
    flex-direction: column;
    align-items: flex-start;
  }
  .record-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
