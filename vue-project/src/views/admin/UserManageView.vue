<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  getUserListApi,
  resetUserPasswordApi,
  updateUserRoleApi,
  updateUserStatusApi,
} from '@/adminApi'
import { useAuthStore } from '@/store/authStore'

const { userInfo } = useAuthStore()

const loading = ref(false)
const rows = ref([])
const total = ref(0)

// 空字符串代表"这个条件不筛选"，发请求前会被丢掉
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  role: '',
  status: '',
})

const roleOptions = [
  { label: '读者', value: 'student' },
  { label: '管理员', value: 'admin' },
]

const statusOptions = [
  { label: '正常', value: 1 },
  { label: '已禁用', value: 0 },
]

const roleLabel = (role) =>
  roleOptions.find((item) => item.value === role)?.label || role

// 自己这一行不能改角色、不能禁用。后端也会拦，这里提前置灰按钮，
// 免得点下去才被拒绝（也是给用户留个"为什么不行"的视觉提示）
const isSelf = (row) => row.id === userInfo.value?.id

async function fetchUsers() {
  loading.value = true
  try {
    // 后端的 keyword/role/status 都是带类型的查询参数，传空字符串会直接 422，
    // 所以"没填"的条件一律不放进参数里
    const params = { page: query.page, page_size: query.page_size }

    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.role) params.role = query.role
    if (query.status !== '') params.status = query.status

    const data = await getUserListApi(params)
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
  fetchUsers()
}

function resetQuery() {
  query.keyword = ''
  query.role = ''
  query.status = ''
  search()
}

async function changeRole(row, role) {
  try {
    await ElMessageBox.confirm(
      `确定把「${row.name}」的角色改为${roleLabel(role)}吗？`,
      '修改角色',
      { type: 'warning', confirmButtonText: '确认修改', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户点了取消
  }

  try {
    await updateUserRoleApi(row.id, role)
    ElMessage.success('角色已更新')
    fetchUsers()
  } catch {
    // 错误提示由请求拦截器统一处理
  }
}

async function toggleStatus(row) {
  const next = row.status === 1 ? 0 : 1
  const action = next === 1 ? '启用' : '禁用'

  try {
    await ElMessageBox.confirm(
      next === 1
        ? `确定启用「${row.name}」的账号吗？`
        : `确定禁用「${row.name}」的账号吗？禁用后对方将无法登录，已登录的也会被踢下线。`,
      `${action}账号`,
      { type: 'warning', confirmButtonText: `确认${action}`, cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  try {
    await updateUserStatusApi(row.id, next)
    ElMessage.success(`账号已${action}`)
    fetchUsers()
  } catch {
    // 错误提示由请求拦截器统一处理
  }
}

const pwdDialog = reactive({
  visible: false,
  userId: null,
  name: '',
  password: '',
  saving: false,
})

function openResetPassword(row) {
  pwdDialog.visible = true
  pwdDialog.userId = row.id
  pwdDialog.name = row.name
  pwdDialog.password = ''
}

async function submitResetPassword() {
  if (pwdDialog.saving) return

  if (pwdDialog.password.length < 6 || pwdDialog.password.length > 32) {
    ElMessage.error('密码长度需为 6-32 位')
    return
  }

  pwdDialog.saving = true
  try {
    await resetUserPasswordApi(pwdDialog.userId, pwdDialog.password)
    ElMessage.success(`已重置「${pwdDialog.name}」的密码，请把新密码告知本人`)
    pwdDialog.visible = false
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    pwdDialog.saving = false
  }
}

onMounted(fetchUsers)
</script>

<template>
  <div class="admin-page">
    <section class="admin-intro">
      <div>
        <span>ADMIN CONSOLE</span>
        <h2>读者管理</h2>
        <p>查看平台注册读者、调整角色与账号状态，操作会立即生效。</p>
      </div>
      <div class="intro-numbers">
        <div><strong>{{ total }}</strong><span>读者总数</span></div>
      </div>
    </section>

    <section class="filter-bar surface">
      <el-input
        v-model="query.keyword"
        clearable
        class="search-input"
        placeholder="搜索账号或姓名"
        @keyup.enter="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="query.role" class="filter-select">
        <el-option label="全部角色" value="" />
        <el-option
          v-for="item in roleOptions"
          :key="item.value"
          :label="item.label"
          :value="item.value"
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
    </section>

    <section class="table-card surface">
      <el-table
        v-loading="loading"
        :data="rows"
        class="user-table"
        empty-text="没有符合条件的读者"
      >
        <el-table-column label="读者" min-width="200">
          <template #default="{ row }">
            <div class="user-cell">
              <span class="avatar">{{ (row.name || row.username).slice(0, 1) }}</span>
              <div>
                <strong>{{ row.name }}</strong>
                <small>{{ row.username }}</small>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'warning' : 'info'" effect="light" size="small">
              {{ roleLabel(row.role) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 1 ? 'success' : 'danger'"
              effect="light"
              size="small"
            >
              {{ row.status === 1 ? '正常' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="联系方式" min-width="180">
          <template #default="{ row }">
            <div class="contact">
              <span>{{ row.email || '—' }}</span>
              <small>{{ row.phone || '—' }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="250" align="right">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(role) => changeRole(row, role)">
              <el-button size="small" :disabled="isSelf(row)">
                改角色<el-icon><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="item in roleOptions"
                    :key="item.value"
                    :command="item.value"
                    :disabled="item.value === row.role"
                  >
                    设为{{ item.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <el-button size="small" @click="openResetPassword(row)">重置密码</el-button>

            <el-button
              size="small"
              text
              :type="row.status === 1 ? 'danger' : 'success'"
              :disabled="isSelf(row)"
              @click="toggleStatus(row)"
            >
              {{ row.status === 1 ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span>共 {{ total }} 位读者</span>
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next"
          @current-change="fetchUsers"
          @size-change="search"
        />
      </div>
    </section>

    <el-dialog v-model="pwdDialog.visible" title="重置密码" width="min(420px, 92vw)">
      <p class="dialog-tip">
        为「{{ pwdDialog.name }}」设置一个新密码。重置不需要原密码，请重置后线下告知本人。
      </p>
      <el-input
        v-model="pwdDialog.password"
        type="password"
        show-password
        maxlength="32"
        placeholder="新密码：6-32 位"
      >
        <template #prefix><el-icon><Key /></el-icon></template>
      </el-input>

      <template #footer>
        <el-button @click="pwdDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="pwdDialog.saving" @click="submitResetPassword">
          确认重置
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
.search-input { width: min(300px, 34%); }
.filter-select { width: 140px; }

.table-card { padding: 4px 4px 14px; overflow: hidden; }
.table-footer { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px 4px; }
.table-footer > span { color: #889693; font-size: 10px; }

.user-cell { display: flex; align-items: center; gap: 10px; }
.user-cell .avatar { width: 34px; height: 34px; display: grid; place-items: center; flex: none; color: white; font-size: 12px; font-weight: 700; background: #2d6461; border-radius: 10px; }
.user-cell strong { display: block; color: #294845; font-size: 12px; }
.user-cell small { display: block; margin-top: 1px; color: #93a09d; font-size: 9px; }
.contact span, .contact small { display: block; }
.contact span { color: #55706c; font-size: 11px; }
.contact small { margin-top: 2px; color: #93a09d; font-size: 9px; }
.dialog-tip { margin-bottom: 14px; color: #6e7e7c; font-size: 12px; line-height: 1.6; }

/* 让 Element Plus 的表格配色跟站内其它卡片一致 */
.admin-page :deep(.el-table) { font-size: 12px; }
.admin-page :deep(.el-table th.el-table__cell) { background: #f6f7f4; color: #517271; font-size: 10px; font-weight: 700; }
.admin-page :deep(.el-table td.el-table__cell) { border-bottom: 1px solid #efefeb; }
.admin-page :deep(.el-table__inner-wrapper::before) { display: none; }

@media (max-width: 900px) {
  .filter-bar { flex-wrap: wrap; }
  .search-input { width: 100%; }
  .filter-select { flex: 1; }
  .table-footer { align-items: flex-start; flex-direction: column; gap: 10px; }
}
</style>
