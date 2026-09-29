<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getUserInfoApi, updateUserInfoApi, uploadFileApi } from '@/authApi'
import { useAuthStore } from '@/store/authStore'

const { userInfo, updateUser } = useAuthStore()

const formRef = ref()
const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)

const form = reactive({
  username: '',
  name: '',
  email: '',
  phone: '',
  avatar: '',
})

const rules = {
  name: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { max: 50, message: '姓名长度不能超过 50 位', trigger: 'blur' },
  ],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
  phone: [{ pattern: /^1[3-9]\d{9}$/, message: '手机号格式不正确', trigger: 'blur' }],
}

// 后端上传接口返回的是相对路径 /uploads/xxx，浏览器直接用不显示，
// 需要拼上后端地址（VITE_API_BASE_URL）；已是完整 http 地址则原样返回
function resolveUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//.test(path)) return path
  return `${import.meta.env.VITE_API_BASE_URL}${path}`
}

const avatarUrl = computed(() => resolveUrl(form.avatar))
const fallbackText = computed(() => (form.name || form.username || '用').slice(0, 1))

function fillForm(user) {
  form.username = user?.username || ''
  form.name = user?.name || ''
  form.email = user?.email || ''
  form.phone = user?.phone || ''
  form.avatar = user?.avatar || ''
}

onMounted(async () => {
  loading.value = true
  try {
    const user = await getUserInfoApi()
    updateUser(user)
    fillForm(user)
  } catch {
    // 接口失败时退回本地缓存，错误提示已由请求拦截器统一处理
    fillForm(userInfo.value)
  } finally {
    loading.value = false
  }
})

// el-upload 的 http-request 自定义上传：拿到返回 url 先存到表单，
// 等用户点「保存」时才真正写进用户资料，避免「上传了但没保存」的空档
async function handleAvatarUpload(options) {
  if (uploading.value) return
  uploading.value = true
  try {
    const result = await uploadFileApi(options.file)
    form.avatar = result.url
    ElMessage.success('头像已上传，记得点击保存')
  } catch {
    // 错误提示已由请求拦截器统一处理
  } finally {
    uploading.value = false
  }
}

// 只放行图片类型并限制大小；后端还有扩展名/大小校验，这里只是提前拦截
function beforeAvatarUpload(file) {
  const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
  if (!allowed.includes(file.type)) {
    ElMessage.error('头像仅支持 JPG / PNG / GIF / WebP 图片')
    return false
  }
  if (file.size / 1024 / 1024 > 5) {
    ElMessage.error('头像大小不能超过 5MB')
    return false
  }
  return true
}

async function save() {
  if (saving.value) return

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    const user = await updateUserInfoApi({
      name: form.name,
      email: form.email,
      phone: form.phone,
      avatar: form.avatar,
    })
    updateUser(user)
    ElMessage.success('个人信息已更新')
  } catch {
    // 错误提示已由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="profile-page">
    <section class="profile-card surface" v-loading="loading">
      <div class="avatar-panel">
        <el-upload
          class="avatar-uploader"
          :show-file-list="false"
          :http-request="handleAvatarUpload"
          :before-upload="beforeAvatarUpload"
          accept="image/*"
        >
          <div class="avatar-box" :class="{ uploading }">
            <img v-if="avatarUrl" :src="avatarUrl" alt="头像" />
            <span v-else class="avatar-placeholder">{{ fallbackText }}</span>
            <div class="avatar-mask">
              <el-icon><Camera /></el-icon>
              <span>{{ uploading ? '上传中…' : '更换头像' }}</span>
            </div>
          </div>
        </el-upload>
        <strong>{{ form.name || form.username }}</strong>
        <p>{{ form.username }} · 支持 JPG / PNG / GIF / WebP，≤ 5MB</p>
      </div>

      <div class="form-panel">
        <div class="panel-head">
          <h2>个人信息</h2>
          <p>更新你的基本资料，账号与角色不可修改</p>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="loading">
          <el-form-item label="账号">
            <el-input :model-value="form.username" disabled>
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>

          <el-form-item label="姓名" prop="name">
            <el-input v-model="form.name" maxlength="50" placeholder="请输入姓名">
              <template #prefix><el-icon><Postcard /></el-icon></template>
            </el-input>
          </el-form-item>

          <div class="form-row">
            <el-form-item label="邮箱" prop="email">
              <el-input v-model="form.email" maxlength="50" placeholder="选填">
                <template #prefix><el-icon><Message /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item label="手机号" prop="phone">
              <el-input v-model="form.phone" maxlength="11" placeholder="选填">
                <template #prefix><el-icon><Iphone /></el-icon></template>
              </el-input>
            </el-form-item>
          </div>

          <div class="panel-actions">
            <el-button type="primary" :loading="saving" @click="save">保存修改</el-button>
          </div>
        </el-form>
      </div>
    </section>
  </div>
</template>

<style scoped>
.profile-page { max-width: 860px; }
.profile-card { display: grid; grid-template-columns: 250px 1fr; overflow: hidden; }

.avatar-panel { display: flex; flex-direction: column; align-items: center; padding: 34px 24px; text-align: center; background: linear-gradient(160deg, #eef7f3, #f8f7f3); border-right: 1px solid var(--line); }
.avatar-uploader :deep(.el-upload) { display: block; }
.avatar-box { width: 116px; height: 116px; display: grid; place-items: center; position: relative; overflow: hidden; margin: 0 auto; background: #2d6461; border-radius: 50%; cursor: pointer; }
.avatar-box img { width: 100%; height: 100%; object-fit: cover; }
.avatar-placeholder { color: white; font-family: Georgia, 'Noto Serif SC', serif; font-size: 42px; font-weight: 600; }
.avatar-mask { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; color: white; font-size: 11px; background: rgba(16, 43, 44, .5); opacity: 0; transition: opacity .2s; }
.avatar-mask .el-icon { font-size: 20px; }
.avatar-box:hover .avatar-mask { opacity: 1; }
.avatar-box.uploading { pointer-events: none; }
.avatar-box.uploading .avatar-mask { opacity: 1; }
.avatar-panel > strong { margin-top: 16px; color: var(--ink); font-family: Georgia, 'Noto Serif SC', serif; font-size: 17px; }
.avatar-panel > p { margin-top: 5px; color: var(--muted); font-size: 10px; line-height: 1.6; }

.form-panel { padding: 28px 30px; }
.panel-head { margin-bottom: 24px; }
.panel-head h2 { color: var(--ink); font-family: Georgia, 'Noto Serif SC', serif; font-size: 19px; }
.panel-head p { margin-top: 4px; color: var(--muted); font-size: 11px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.form-panel :deep(.el-form-item__label) { padding-bottom: 6px; color: #345452; font-size: 12px; font-weight: 700; }
.form-panel :deep(.el-input__prefix) { color: #7b918e; }
.panel-actions { display: flex; justify-content: flex-end; padding-top: 6px; }

@media (max-width: 640px) {
  .profile-card { grid-template-columns: 1fr; }
  .avatar-panel { border-right: 0; border-bottom: 1px solid var(--line); }
  .form-row { grid-template-columns: 1fr; gap: 0; }
  .form-panel { padding: 22px 18px; }
}
</style>
