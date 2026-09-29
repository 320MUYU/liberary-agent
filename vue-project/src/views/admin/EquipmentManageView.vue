<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createEquipmentApi,
  deleteEquipmentApi,
  getAdminEquipmentListApi,
  updateEquipmentApi,
} from '@/adminApi'
import {
  equipmentStatusMap,
  labHealthyRate,
  labUnitCount,
  labs,
  loadLabs,
  overallHealthyRate,
} from '@/store/labStore'

const loading = ref(false)
const rows = ref([])
const total = ref(0)

// '' 表示不限定实验室，查全平台
const selectedLabId = ref('')
const query = reactive({ page: 1, page_size: 10, keyword: '', status: '' })

const statusOptions = Object.entries(equipmentStatusMap).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

const labNameMap = computed(() => Object.fromEntries(labs.map((lab) => [lab.id, lab.name])))

// 顶部统计走 store 里的完整数据，表格走接口的分页数据 —— 两个数据源是有意的：
// 接口每页最多 100 条，用它算"总台数"会算少；store 里的 labs 是全量的，
// 用它算统计才是准的。表格则必须走接口，否则筛选和分页都得在前端重做一遍。
const currentLab = computed(() =>
  selectedLabId.value === '' ? null : labs.find((lab) => lab.id === selectedLabId.value) || null,
)

const stats = computed(() => {
  const list = currentLab.value
    ? currentLab.value.equipments || []
    : labs.flatMap((lab) => lab.equipments || [])

  return {
    kinds: list.length,
    units: list.reduce((sum, item) => sum + item.total, 0),
    available: list.reduce((sum, item) => sum + item.available, 0),
    healthy: currentLab.value ? labHealthyRate(currentLab.value) : overallHealthyRate(),
  }
})

async function fetchEquipments() {
  loading.value = true
  try {
    const params = { page: query.page, page_size: query.page_size }
    if (selectedLabId.value !== '') params.lab_id = selectedLabId.value
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.status) params.status = query.status

    const data = await getAdminEquipmentListApi(params)
    rows.value = data.items
    total.value = data.total
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  fetchEquipments()
}

function resetQuery() {
  query.keyword = ''
  query.status = ''
  search()
}

function changeLab() {
  // 换了实验室，页码要退回第一页，否则可能停在一个新筛选下并不存在的页码上
  search()
}

// 管理端改完数据后刷新 store，学生端的台数与完好率会跟着一起更新
async function refreshAll() {
  await loadLabs(true).catch(() => {})

  // 选中的实验室可能刚刚被删掉了，这时要退回"全部实验室"，
  // 否则下拉框会显示空白、表格也查不出东西
  if (selectedLabId.value !== '' && !labs.some((lab) => lab.id === selectedLabId.value)) {
    selectedLabId.value = ''
  }

  await fetchEquipments()
}

// ---------------- 新增 / 编辑 ----------------

const formRef = ref()
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref(null)

const form = reactive({
  lab_id: null,
  name: '',
  model: '',
  total: 1,
  available: 1,
  status: 'normal',
})

// 可用数量不能大于总数量：后端 EquipmentCreateRequest 里也有同样的校验，
// 这里提前拦一下，用户不用等一个来回才知道填错了
function validateAvailable(rule, value, callback) {
  if (value === null || value === undefined) {
    callback(new Error('请输入可用数量'))
    return
  }
  if (value > form.total) {
    callback(new Error('可用数量不能大于总数量'))
    return
  }
  callback()
}

const formRules = {
  lab_id: [{ required: true, message: '请选择所属实验室', trigger: 'change' }],
  name: [
    { required: true, message: '请输入设备名称', trigger: 'blur' },
    { max: 50, message: '名称不能超过 50 个字符', trigger: 'blur' },
  ],
  model: [{ max: 50, message: '型号不能超过 50 个字符', trigger: 'blur' }],
  total: [
    { required: true, message: '请输入总数量', trigger: 'blur' },
    {
      // 把总数从 8 改成 3 时，可用数量可能还停在 6。改的是 total 这个字段，
      // 所以 available 自己的校验不会自动跑，这里手动让它重新校验一次
      validator: (rule, value, callback) => {
        if (form.available > value) {
          formRef.value?.validateField('available').catch(() => {})
        }
        callback()
      },
      trigger: 'change',
    },
  ],
  available: [{ validator: validateAvailable, trigger: 'change' }],
}

function resetForm() {
  Object.assign(form, {
    // 在当前选中的实验室下点"新增"，默认就挂到这间实验室，省一次选择
    lab_id: currentLab.value?.id ?? labs[0]?.id ?? null,
    name: '',
    model: '',
    total: 1,
    available: 1,
    status: 'normal',
  })
  formRef.value?.clearValidate()
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    lab_id: row.lab_id,
    name: row.name,
    model: row.model || '',
    total: row.total,
    available: row.available,
    status: row.status,
  })
  formRef.value?.clearValidate()
  dialogVisible.value = true
}

async function submit() {
  if (saving.value) return

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    const payload = { ...form, model: form.model || null }

    if (editingId.value) {
      await updateEquipmentApi(editingId.value, payload)
      ElMessage.success('设备已更新')
    } else {
      await createEquipmentApi(payload)
      ElMessage.success('设备已新增')
    }

    dialogVisible.value = false
    await refreshAll()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name}」吗？删除后无法恢复。`,
      '删除设备',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return // 用户点了取消
  }

  try {
    await deleteEquipmentApi(row.id)
    ElMessage.success(`已删除「${row.name}」`)
    await refreshAll()
  } catch {
    // 错误提示由请求拦截器统一处理
  }
}

onMounted(async () => {
  // 实验室下拉和顶部统计都要全量数据，所以强制刷新一次
  await loadLabs(true).catch(() => {})
  fetchEquipments()
})
</script>

<template>
  <div class="admin-page">
    <section class="admin-intro">
      <div>
        <span>ADMIN CONSOLE</span>
        <h2>设备管理</h2>
        <p>维护各实验室的设备清单、数量与状态，设备完好率会同步更新到学生端。</p>
      </div>
      <div class="intro-numbers">
        <div><strong>{{ stats.kinds }}</strong><span>设备种类</span></div>
        <div><strong>{{ stats.units }}</strong><span>设备台数</span></div>
        <div><strong>{{ stats.available }}</strong><span>当前可用</span></div>
        <div><strong>{{ stats.healthy }}%</strong><span>设备完好率</span></div>
      </div>
    </section>

    <section class="filter-bar surface">
      <el-select v-model="selectedLabId" class="lab-select" @change="changeLab">
        <el-option label="全部实验室" value="" />
        <el-option
          v-for="lab in labs"
          :key="lab.id"
          :label="`${lab.name}（${labUnitCount(lab)} 台）`"
          :value="lab.id"
        />
      </el-select>

      <el-input
        v-model="query.keyword"
        clearable
        class="search-input"
        placeholder="搜索设备名称或型号"
        @keyup.enter="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="query.status" class="filter-select">
        <el-option label="全部状态" value="" />
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>

      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="resetQuery">重置</el-button>
      <el-button type="primary" plain class="create-button" @click="openCreate">
        <el-icon><Plus /></el-icon>新增设备
      </el-button>
    </section>

    <section class="table-card surface">
      <el-table
        v-loading="loading"
        :data="rows"
        empty-text="没有符合条件的设备"
      >
        <el-table-column label="设备" min-width="220">
          <template #default="{ row }">
            <div class="equipment-cell">
              <strong>{{ row.name }}</strong>
              <small>{{ row.model || '未填写型号' }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="所属实验室" min-width="160">
          <template #default="{ row }">{{ labNameMap[row.lab_id] || '—' }}</template>
        </el-table-column>

        <el-table-column label="可用 / 总数" width="120">
          <template #default="{ row }">
            <span :class="{ 'is-low': row.available === 0 }">{{ row.available }} / {{ row.total }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="equipmentStatusMap[row.status]?.type || 'info'"
              effect="light"
              size="small"
            >
              {{ equipmentStatusMap[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="150" align="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span>共 {{ total }} 条设备记录</span>
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next"
          @current-change="fetchEquipments"
          @size-change="search"
        />
      </div>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑设备' : '新增设备'"
      width="min(560px, 94vw)"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-position="top">
        <el-form-item label="所属实验室" prop="lab_id">
          <el-select v-model="form.lab_id" class="full-width" placeholder="请选择实验室">
            <el-option v-for="lab in labs" :key="lab.id" :label="lab.name" :value="lab.id" />
          </el-select>
        </el-form-item>

        <div class="form-row">
          <el-form-item label="设备名称" prop="name">
            <el-input v-model="form.name" maxlength="50" placeholder="如：图形工作站" />
          </el-form-item>
          <el-form-item label="型号" prop="model">
            <el-input v-model="form.model" maxlength="50" placeholder="选填" />
          </el-form-item>
        </div>

        <div class="form-row">
          <el-form-item label="总数量" prop="total">
            <el-input-number v-model="form.total" :min="1" :max="9999" class="number-input" />
          </el-form-item>
          <el-form-item label="可用数量" prop="available">
            <el-input-number v-model="form.available" :min="0" :max="9999" class="number-input" />
          </el-form-item>
        </div>

        <el-form-item label="状态">
          <el-select v-model="form.status" class="full-width">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">
          {{ editingId ? '保存修改' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-page { display: flex; flex-direction: column; gap: 18px; }
.admin-intro { min-height: 132px; display: flex; align-items: center; justify-content: space-between; gap: 25px; padding: 26px 32px; position: relative; overflow: hidden; color: white; background: #1d5552; border-radius: 17px; }
.admin-intro::after { content: ''; position: absolute; right: -45px; top: -105px; width: 260px; height: 260px; border: 1px solid rgba(126, 215, 185, .18); border-radius: 50%; }
.admin-intro > div { position: relative; z-index: 1; }
.admin-intro > div:first-child > span { color: #81c9b3; font-size: 8px; font-weight: 800; letter-spacing: 1.8px; }
.admin-intro h2 { margin-top: 8px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; font-weight: 600; }
.admin-intro p { margin-top: 7px; max-width: 340px; color: #abc7c3; font-size: 11px; line-height: 1.6; }
.intro-numbers { display: flex; gap: 30px; margin-right: 18px; text-align: center; }
.intro-numbers strong, .intro-numbers span { display: block; }
.intro-numbers strong { color: #a4e5cf; font-family: Georgia, serif; font-size: 22px; }
.intro-numbers span { margin-top: 2px; color: #9bbab6; font-size: 8px; }

.filter-bar { display: flex; align-items: center; gap: 11px; padding: 14px; }
.lab-select { width: 210px; }
.search-input { width: min(240px, 26%); }
.filter-select { width: 130px; }
.create-button { margin-left: auto; }

.table-card { padding: 4px 4px 14px; overflow: hidden; }
.table-footer { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px 4px; }
.table-footer > span { color: #889693; font-size: 10px; }

.equipment-cell strong { display: block; color: #294845; font-size: 12px; }
.equipment-cell small { display: block; margin-top: 1px; color: #93a09d; font-size: 9px; }
/* 一台都不可用是需要注意的情况，标红提醒 */
.is-low { color: #c1665f; font-weight: 700; }

.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.full-width, .number-input { width: 100%; }
.admin-page :deep(.el-form-item__label) { padding-bottom: 6px; color: #345452; font-size: 12px; font-weight: 700; }

.admin-page :deep(.el-table) { font-size: 12px; }
.admin-page :deep(.el-table th.el-table__cell) { background: #f6f7f4; color: #517271; font-size: 10px; font-weight: 700; }
.admin-page :deep(.el-table td.el-table__cell) { border-bottom: 1px solid #efefeb; }
.admin-page :deep(.el-table__inner-wrapper::before) { display: none; }

@media (max-width: 1100px) {
  .intro-numbers { gap: 18px; }
}
@media (max-width: 900px) {
  .admin-intro { align-items: flex-start; flex-direction: column; }
  .intro-numbers { margin-right: 0; }
  .filter-bar { flex-wrap: wrap; }
  .lab-select, .search-input { width: 100%; }
  .filter-select { flex: 1; }
  .create-button { margin-left: 0; }
  .form-row { grid-template-columns: 1fr; gap: 0; }
  .table-footer { align-items: flex-start; flex-direction: column; gap: 10px; }
}
</style>
