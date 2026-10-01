<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createLabApi,
  deleteLabApi,
  getAdminLabListApi,
  updateLabApi,
} from '@/adminApi'
import { uploadFileApi } from '@/authApi'
import { labStatusMap, labUnitCount, labs, loadLabs } from '@/store/labStore'
import { resolveAssetUrl } from '@/utils/url.js'

const loading = ref(false)
const rows = ref([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  category: '',
  status: '',
})

// 下拉选项直接从公共的实验室列表里取，不另外维护一份："有哪些类别"
// 本来就是数据里长出来的，写死在代码里迟早和管理员新加的类别对不上
const categoryOptions = computed(() => [...new Set(labs.map((lab) => lab.category))].sort())
const statusOptions = Object.entries(labStatusMap).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

async function fetchLabs() {
  loading.value = true
  try {
    const params = { page: query.page, page_size: query.page_size }
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.category) params.category = query.category
    if (query.status) params.status = query.status

    const data = await getAdminLabListApi(params)
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
  fetchLabs()
}

function resetQuery() {
  query.keyword = ''
  query.category = ''
  query.status = ''
  search()
}

// 管理端改完数据后，顺手把公共列表也刷新一遍：
// 这样切到学生端页面看到的就是最新的，不会出现"刚改完还是旧的"
async function refreshAll() {
  await loadLabs(true).catch(() => {})
  await fetchLabs()
}

// ---------------- 新增 / 编辑 ----------------

const formRef = ref()
const dialogVisible = ref(false)
const saving = ref(false)
const uploading = ref(false)
const editingId = ref(null)

const form = reactive({
  name: '',
  code: '',
  building: '',
  floor: '',
  capacity: 20,
  category: '',
  status: 'available',
  description: '',
  cover: '',
})

const rules = {
  name: [
    { required: true, message: '请输入空间名称', trigger: 'blur' },
    { max: 50, message: '名称不能超过 50 个字符', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入房间号', trigger: 'blur' },
    { max: 20, message: '房间号不能超过 20 个字符', trigger: 'blur' },
  ],
  building: [{ required: true, message: '请输入所在馆区', trigger: 'blur' }],
  floor: [{ required: true, message: '请输入楼层', trigger: 'blur' }],
  capacity: [{ required: true, message: '请输入可容纳人数', trigger: 'blur' }],
  category: [{ required: true, message: '请输入或选择空间类型', trigger: 'change' }],
}

function resetForm() {
  Object.assign(form, {
    name: '',
    code: '',
    building: '',
    floor: '',
    capacity: 20,
    category: '',
    status: 'available',
    description: '',
    cover: '',
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
    name: row.name,
    code: row.code,
    building: row.building,
    floor: row.floor,
    capacity: row.capacity,
    category: row.category,
    status: row.status,
    description: row.description || '',
    cover: row.cover || '',
  })
  formRef.value?.clearValidate()
  dialogVisible.value = true
}

// 封面图上传：拿到的是 url 先存进表单，等点保存才真正写进实验室
async function handleCoverUpload(options) {
  if (uploading.value) return
  uploading.value = true
  try {
    const result = await uploadFileApi(options.file)
    form.cover = result.url
    ElMessage.success('封面已上传，记得点击保存')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    uploading.value = false
  }
}

function beforeCoverUpload(file) {
  const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
  if (!allowed.includes(file.type)) {
    ElMessage.error('封面仅支持 JPG / PNG / GIF / WebP 图片')
    return false
  }
  if (file.size / 1024 / 1024 > 5) {
    ElMessage.error('封面大小不能超过 5MB')
    return false
  }
  return true
}

async function submit() {
  if (saving.value) return

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    // 后端是 PUT 全量更新，所以这里把整份表单发过去；空字符串统一转成 null，
    // 免得把"没填"存成一串空字符串
    const payload = {
      ...form,
      description: form.description || null,
      cover: form.cover || null,
    }

    if (editingId.value) {
      await updateLabApi(editingId.value, payload)
      ElMessage.success('学习空间已更新')
    } else {
      await createLabApi(payload)
      ElMessage.success('学习空间已创建')
    }

    dialogVisible.value = false
    await refreshAll()
  } catch {
    // 错误提示由请求拦截器统一处理（房间号重复会提示 409 的文案）
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  const equipmentCount = row.equipments?.length || 0
  const tip = equipmentCount
    ? `确定删除「${row.name}」吗？它名下的 ${equipmentCount} 种设施会一起被删除，且无法恢复。`
    : `确定删除「${row.name}」吗？删除后无法恢复。`

  try {
    await ElMessageBox.confirm(tip, '删除学习空间', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return // 用户点了取消
  }

  try {
    await deleteLabApi(row.id)
    ElMessage.success(
      equipmentCount ? `已删除「${row.name}」及其 ${equipmentCount} 种设施` : `已删除「${row.name}」`,
    )
    await refreshAll()
  } catch {
    // 错误提示由请求拦截器统一处理
  }
}

onMounted(async () => {
  // 强制刷新一次：类别下拉要的是完整列表，可能比当前页更全
  await loadLabs(true).catch(() => {})
  fetchLabs()
})
</script>

<template>
  <div class="admin-page">
    <section class="admin-intro">
      <div>
        <span>ADMIN CONSOLE</span>
        <h2>空间管理</h2>
        <p>维护学习空间的基本信息与开放状态，改动会立刻反映到读者端。</p>
      </div>
      <div class="intro-numbers">
        <div><strong>{{ total }}</strong><span>空间总数</span></div>
      </div>
    </section>

    <section class="filter-bar surface">
      <el-input
        v-model="query.keyword"
        clearable
        class="search-input"
        placeholder="搜索名称、房间号或馆区"
        @keyup.enter="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="query.category" class="filter-select">
        <el-option label="全部类型" value="" />
        <el-option
          v-for="item in categoryOptions"
          :key="item"
          :label="item"
          :value="item"
        />
      </el-select>

      <el-select v-model="query.status" class="filter-select">
        <el-option label="全部状态" value="" />
        <el-option
          v-for="item in statusOptions"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>

      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="resetQuery">重置</el-button>
      <el-button type="primary" plain class="create-button" @click="openCreate">
        <el-icon><Plus /></el-icon>新增空间
      </el-button>
    </section>

    <section class="table-card surface">
      <el-table
        v-loading="loading"
        :data="rows"
        class="lab-table"
        empty-text="没有符合条件的学习空间"
      >
        <el-table-column label="学习空间" min-width="230">
          <template #default="{ row }">
            <div class="lab-cell">
              <span class="thumb">
                <img v-if="row.cover" :src="resolveAssetUrl(row.cover)" :alt="row.name" />
                <el-icon v-else><School /></el-icon>
              </span>
              <div>
                <strong>{{ row.name }}</strong>
                <small>{{ row.code }} · {{ row.category }}</small>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="位置" min-width="150">
          <template #default="{ row }">{{ row.building }} · {{ row.floor }}</template>
        </el-table-column>

        <el-table-column label="容量" width="90">
          <template #default="{ row }">{{ row.capacity }} 人</template>
        </el-table-column>

        <el-table-column label="设施" width="90">
          <template #default="{ row }">{{ labUnitCount(row) }} 台</template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="labStatusMap[row.status]?.type || 'info'" effect="light" size="small">
              {{ labStatusMap[row.status]?.label || row.status }}
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
        <span>共 {{ total }} 个学习空间</span>
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next"
          @current-change="fetchLabs"
          @size-change="search"
        />
      </div>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑学习空间' : '新增学习空间'"
      width="min(620px, 94vw)"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-row">
          <el-form-item label="空间名称" prop="name">
            <el-input v-model="form.name" maxlength="50" placeholder="如：知行研讨室" />
          </el-form-item>
          <el-form-item label="房间号" prop="code">
            <el-input v-model="form.code" maxlength="20" placeholder="如：A-301" />
          </el-form-item>
        </div>

        <div class="form-row">
          <el-form-item label="所在馆区" prop="building">
            <el-input v-model="form.building" maxlength="50" placeholder="如：信息楼 A区" />
          </el-form-item>
          <el-form-item label="楼层" prop="floor">
            <el-input v-model="form.floor" maxlength="10" placeholder="如：3F" />
          </el-form-item>
        </div>

        <div class="form-row">
          <el-form-item label="可容纳人数" prop="capacity">
            <el-input-number v-model="form.capacity" :min="1" :max="1000" class="number-input" />
          </el-form-item>
          <el-form-item label="空间类型" prop="category">
            <!-- allow-create：管理员可以填一个全新的类别，不用改代码 -->
            <el-select
              v-model="form.category"
              filterable
              allow-create
              default-first-option
              placeholder="选择或输入空间类型"
              class="full-width"
            >
              <el-option v-for="item in categoryOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
        </div>

        <div class="form-row">
          <el-form-item label="状态">
            <el-select v-model="form.status" class="full-width">
              <el-option
                v-for="item in statusOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="封面图">
            <div class="cover-field">
              <el-upload
                :show-file-list="false"
                :http-request="handleCoverUpload"
                :before-upload="beforeCoverUpload"
                accept="image/*"
              >
                <el-button :loading="uploading">
                  {{ form.cover ? '更换封面' : '上传封面' }}
                </el-button>
              </el-upload>
              <img v-if="form.cover" class="cover-preview" :src="resolveAssetUrl(form.cover)" alt="封面预览" />
            </div>
          </el-form-item>
        </div>

        <el-form-item label="简介">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="255"
            show-word-limit
            placeholder="一句话说明这个学习空间适合做什么"
          />
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
.admin-intro { min-height: 132px; display: flex; align-items: center; justify-content: space-between; gap: 25px; padding: 26px 32px; position: relative; overflow: hidden; color: white; background: var(--navy-900); border-radius: 17px; box-shadow: var(--shadow-md); }
.admin-intro::after { content: ''; position: absolute; right: -45px; top: -105px; width: 260px; height: 260px; border: 1px solid rgba(126, 215, 185, .18); border-radius: 50%; }
.admin-intro > div { position: relative; z-index: 1; }
.admin-intro > div:first-child > span { color: #e5be78; font-size: 8px; font-weight: 800; letter-spacing: 1.8px; }
.admin-intro h2 { margin-top: 8px; color: #fff; font-size: 25px; font-weight: 600; }
.admin-intro p { margin-top: 7px; color: #c5d0d8; font-size: 11px; }
.intro-numbers { margin-right: 18px; text-align: center; }
.intro-numbers strong, .intro-numbers span { display: block; }
.intro-numbers strong { color: #f0ca87; font-family: Georgia, serif; font-size: 24px; }
.intro-numbers span { margin-top: 2px; color: #9bbab6; font-size: 8px; }

.filter-bar { display: flex; align-items: center; gap: 11px; padding: 14px; }
.search-input { width: min(280px, 30%); }
.filter-select { width: 140px; }
.create-button { margin-left: auto; }

.table-card { padding: 4px 4px 14px; overflow: hidden; }
.table-footer { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px 4px; }
.table-footer > span { color: #889693; font-size: 10px; }

.lab-cell { display: flex; align-items: center; gap: 10px; }
.lab-cell .thumb { width: 42px; height: 34px; display: grid; place-items: center; flex: none; overflow: hidden; color: #6c8b86; font-size: 17px; background: #eef4f1; border-radius: 8px; }
.lab-cell .thumb img { width: 100%; height: 100%; object-fit: cover; }
.lab-cell strong { display: block; color: #294845; font-size: 12px; }
.lab-cell small { display: block; margin-top: 1px; color: #93a09d; font-size: 9px; }

.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.full-width, .number-input { width: 100%; }
.cover-field { display: flex; align-items: center; gap: 12px; }
.cover-preview { width: 76px; height: 54px; object-fit: cover; border: 1px solid var(--line); border-radius: 8px; }
.admin-page :deep(.el-form-item__label) { padding-bottom: 6px; color: #345452; font-size: 12px; font-weight: 700; }

/* 让 Element Plus 的表格配色跟站内其它卡片一致 */
.admin-page :deep(.el-table) { font-size: 12px; }
.admin-page :deep(.el-table th.el-table__cell) { background: #f6f7f4; color: #517271; font-size: 10px; font-weight: 700; }
.admin-page :deep(.el-table td.el-table__cell) { border-bottom: 1px solid #efefeb; }
.admin-page :deep(.el-table__inner-wrapper::before) { display: none; }

@media (max-width: 900px) {
  .filter-bar { flex-wrap: wrap; }
  .search-input { width: 100%; }
  .filter-select { flex: 1; }
  .create-button { margin-left: 0; }
  .form-row { grid-template-columns: 1fr; gap: 0; }
  .table-footer { align-items: flex-start; flex-direction: column; gap: 10px; }
}
</style>
