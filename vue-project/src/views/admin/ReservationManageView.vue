<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getAdminReservationListApi, reviewReservationApi } from '@/adminApi'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 10, keyword: '', status: 'pending' })

const statusMeta = {
  pending: { label: '待审核', type: 'warning' },
  approved: { label: '已通过', type: 'success' },
  rejected: { label: '已驳回', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

async function fetchReservations() {
  loading.value = true
  try {
    const params = { page: query.page, page_size: query.page_size }
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.status) params.status = query.status
    const data = await getAdminReservationListApi(params)
    rows.value = data.items
    total.value = data.total
  } catch {
    // 请求层统一显示错误。
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  fetchReservations()
}

function resetQuery() {
  query.keyword = ''
  query.status = 'pending'
  search()
}

const review = reactive({ visible: false, row: null, status: 'approved', note: '', saving: false })
const reviewTitle = computed(() => review.status === 'approved' ? '通过预约' : '驳回预约')

function openReview(row, status) {
  review.row = row
  review.status = status
  review.note = ''
  review.visible = true
}

async function submitReview() {
  if (review.saving) return
  if (review.status === 'rejected' && !review.note.trim()) {
    ElMessage.warning('请填写驳回理由')
    return
  }
  review.saving = true
  try {
    await reviewReservationApi(review.row.id, {
      status: review.status,
      review_note: review.note.trim() || null,
    })
    ElMessage.success(review.status === 'approved' ? '预约已通过' : '预约已驳回')
    review.visible = false
    await fetchReservations()
  } catch {
    // 后端会提示时段冲突、重复审核等具体原因。
  } finally {
    review.saving = false
  }
}

function formatCreated(value) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

onMounted(fetchReservations)
</script>

<template>
  <div class="admin-page">
    <section class="admin-intro">
      <div>
        <span>ADMIN CONSOLE</span>
        <h2>预约审核</h2>
        <p>集中查看读者申请，核对学习空间、人数和使用时间后完成审核。</p>
      </div>
      <div class="intro-numbers"><div><strong>{{ total }}</strong><span>{{ statusMeta[query.status]?.label || '预约' }}</span></div></div>
    </section>

    <section class="filter-bar surface">
      <el-input v-model="query.keyword" clearable class="search-input" placeholder="搜索学习空间、房间号或申请人" @keyup.enter="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="query.status" class="filter-select" @change="search">
        <el-option label="全部状态" value="" />
        <el-option v-for="(meta, value) in statusMeta" :key="value" :label="meta.label" :value="value" />
      </el-select>
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="resetQuery">重置</el-button>
    </section>

    <section class="table-card surface">
      <el-table v-loading="loading" :data="rows" empty-text="没有符合条件的预约">
        <el-table-column label="申请人" min-width="130">
          <template #default="{ row }"><strong class="applicant">{{ row.applicant_name }}</strong><small class="muted">ID {{ row.applicant_id }}</small></template>
        </el-table-column>
        <el-table-column label="学习空间" min-width="190">
          <template #default="{ row }"><strong class="lab-name">{{ row.lab_name }}</strong><small class="muted">{{ row.lab_code }}</small></template>
        </el-table-column>
        <el-table-column label="预约时间" min-width="190">
          <template #default="{ row }"><span>{{ row.date }}</span><small class="muted">{{ row.start }} — {{ row.end }}</small></template>
        </el-table-column>
        <el-table-column prop="people" label="人数" width="75"><template #default="{ row }">{{ row.people }} 人</template></el-table-column>
        <el-table-column label="用途与说明" min-width="220" show-overflow-tooltip>
          <template #default="{ row }"><span>{{ row.purpose }}</span><small v-if="row.note" class="muted note">{{ row.note }}</small></template>
        </el-table-column>
        <el-table-column label="状态" width="95">
          <template #default="{ row }"><el-tag :type="statusMeta[row.status]?.type || 'info'" effect="light">{{ statusMeta[row.status]?.label || row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="申请时间" min-width="145"><template #default="{ row }">{{ formatCreated(row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" fixed="right" width="150">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button size="small" type="success" @click="openReview(row, 'approved')">通过</el-button>
              <el-button size="small" type="danger" plain @click="openReview(row, 'rejected')">驳回</el-button>
            </template>
            <span v-else class="review-note" :title="row.review_note || ''">{{ row.review_note || '已处理' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-row">
        <el-pagination v-model:current-page="query.page" v-model:page-size="query.page_size" :total="total" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next" @current-change="fetchReservations" @size-change="search" />
      </div>
    </section>

    <el-dialog v-model="review.visible" :title="reviewTitle" width="min(520px, 92vw)" :close-on-click-modal="!review.saving">
      <template v-if="review.row">
        <div class="review-summary">
          <strong>{{ review.row.applicant_name }} · {{ review.row.lab_name }}</strong>
          <p>{{ review.row.date }} {{ review.row.start }} — {{ review.row.end }} · {{ review.row.people }} 人</p>
          <p>用途：{{ review.row.purpose }}</p>
        </div>
        <el-form label-position="top">
          <el-form-item :label="review.status === 'rejected' ? '驳回理由' : '审核意见（选填）'" :required="review.status === 'rejected'">
            <el-input v-model="review.note" type="textarea" :rows="4" maxlength="500" show-word-limit :placeholder="review.status === 'rejected' ? '请说明未通过原因，读者可在预约详情中查看' : '可填写注意事项或使用要求'" />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button :disabled="review.saving" @click="review.visible = false">取消</el-button>
        <el-button :type="review.status === 'approved' ? 'success' : 'danger'" :loading="review.saving" @click="submitReview">确认{{ review.status === 'approved' ? '通过' : '驳回' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-page { display: flex; flex-direction: column; gap: 20px; }
.admin-intro { min-height: 145px; display: flex; align-items: center; justify-content: space-between; padding: 27px 31px; color: white; background: linear-gradient(120deg, var(--navy-950), var(--navy-800)); border-radius: 17px; box-shadow: var(--shadow-md); }
.admin-intro > div > span { color: #e5be78; font-size: 9px; font-weight: 800; letter-spacing: 2px; }.admin-intro h2 { margin-top: 7px; color: #fff; font-size: 25px; }.admin-intro p { margin-top: 8px; color: #c5d0d8; font-size: 11px; }.intro-numbers { min-width: 110px; text-align: center; }.intro-numbers strong, .intro-numbers span { display: block; }.intro-numbers strong { color: #f0ca87; font-family: Georgia, serif; font-size: 32px; }.intro-numbers span { margin-top: 3px; color: #bdc9d1; font-size: 10px; }
.filter-bar { display: flex; align-items: center; gap: 10px; padding: 16px 18px; }.search-input { width: min(340px, 100%); }.filter-select { width: 160px; }.table-card { overflow: hidden; }.pagination-row { display: flex; justify-content: flex-end; padding: 17px 20px; border-top: 1px solid #eceee9; }
.applicant, .lab-name { display: block; color: var(--navy-900); font-size: 12px; }.muted { display: block; margin-top: 4px; overflow: hidden; color: #768894; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.note { max-width: 210px; }.review-note { display: block; overflow: hidden; color: #71838f; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.review-summary { margin-bottom: 20px; padding: 15px 17px; background: var(--gold-100); border-radius: 10px; }.review-summary strong { color: var(--navy-900); font-size: 13px; }.review-summary p { margin-top: 6px; color: #687a88; font-size: 11px; }
@media (max-width: 700px) { .admin-intro { align-items: flex-start; padding: 23px; }.intro-numbers { min-width: 70px; }.filter-bar { align-items: stretch; flex-wrap: wrap; }.search-input { width: 100%; }.filter-select { flex: 1; }.pagination-row { overflow-x: auto; justify-content: flex-start; } }
</style>
