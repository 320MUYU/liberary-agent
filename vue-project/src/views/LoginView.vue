<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { loginApi } from '@/authApi'
import AuthBrandPanel from '@/components/AuthBrandPanel.vue'
import { BRAND } from '@/config/brand'
import { useAuthStore } from '@/store/authStore'

const route = useRoute()
const router = useRouter()
const formRef = ref()
const loading = ref(false)
const form = reactive({
  // 从注册页跳过来时会带上 username，这里回填省得用户再输一遍
  username: typeof route.query.username === 'string' ? route.query.username : '',
  password: '',
})
const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const { saveLoginData } = useAuthStore()

function getRedirectPath() {
  const redirect = route.query.redirect
  return typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/'
}

async function login() {
  if (loading.value) return

  const valid = await formRef.value.validate().catch(() => false)

  if (!valid) return

  loading.value = true

  try {
    const loginData = await loginApi(form)
    saveLoginData(loginData)
    ElMessage.success('登录成功')
    await router.replace(getRedirectPath())
  } catch {
    // 请求错误由 Axios 响应拦截器统一提示。
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <AuthBrandPanel />

    <section class="login-form-panel">
      <div class="login-card">
        <span class="mobile-brand">{{ BRAND.name }}</span>
        <h2>欢迎回来</h2>
        <p class="form-intro">请使用图书馆学习空间预约账号登录</p>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="login">
          <el-form-item label="账号" prop="username">
            <el-input v-model="form.username" size="large" autocomplete="username" placeholder="请输入账号">
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" size="large" type="password" show-password autocomplete="current-password" placeholder="请输入密码">
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>

          <el-button class="login-button" type="primary" size="large" :loading="loading" @click="login">
            登录平台 <el-icon v-if="!loading"><Right /></el-icon>
          </el-button>
        </el-form>

        <p class="register-entry">
          还没有账号？<router-link :to="{ name: 'register' }">立即注册</router-link>
        </p>

        <p class="support-text"><el-icon><InfoFilled /></el-icon> 如无法登录，请联系图书馆管理员</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page { min-height: 100vh; display: grid; grid-template-columns: minmax(420px, 1.05fr) minmax(420px, .95fr); background: var(--paper); }
.login-brand-panel { min-height: 100vh; display: flex; flex-direction: column; position: relative; overflow: hidden; padding: 46px 58px 34px; color: white; background: #123b3a; }
.login-brand-panel::before { content: ''; position: absolute; inset: 0; background: radial-gradient(circle at 78% 70%, rgba(126, 215, 185, .18), transparent 37%), linear-gradient(145deg, rgba(255,255,255,.025), transparent 45%); }
.brand-lockup { display: flex; align-items: center; gap: 13px; position: relative; z-index: 2; }.brand-lockup strong { display: block; font-family: Georgia, serif; font-size: 24px; letter-spacing: .4px; }.brand-lockup small { display: block; margin-top: 1px; color: #91afad; font-size: 10px; letter-spacing: .9px; }
.brand-mark { width: 42px; height: 42px; display: flex; align-items: end; justify-content: center; gap: 3px; padding: 9px; border-radius: 13px; background: var(--mint); transform: rotate(-2deg); }.brand-mark span { width: 5px; display: block; background: #143c3b; border-radius: 5px 5px 2px 2px; }.brand-mark span:nth-child(1) { height: 12px; }.brand-mark span:nth-child(2) { height: 22px; }.brand-mark span:nth-child(3) { height: 16px; }
.brand-copy { max-width: 590px; position: relative; z-index: 2; margin: auto 0; padding-bottom: 82px; }.eyebrow { color: #87cbb5; font-size: 10px; font-weight: 800; letter-spacing: 2.7px; }.brand-copy h1 { margin-top: 22px; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(38px, 4vw, 61px); font-weight: 500; line-height: 1.22; letter-spacing: 1px; }.brand-copy p { max-width: 480px; margin-top: 24px; color: #a9c2c0; font-size: 14px; line-height: 1.9; }
.lab-visual { width: 360px; height: 360px; position: absolute; right: -30px; bottom: -42px; opacity: .72; }.orbit { position: absolute; border: 1px solid rgba(148, 222, 198, .2); border-radius: 50%; }.orbit-one { width: 330px; height: 330px; right: -10px; bottom: -10px; }.orbit-two { width: 220px; height: 220px; right: 45px; bottom: 45px; }.flask { width: 94px; height: 150px; position: absolute; right: 118px; bottom: 100px; }.flask > i { width: 31px; height: 52px; display: block; margin: auto; border: 5px solid #86d9bd; border-width: 0 5px; }.flask > b { width: 94px; height: 94px; display: block; position: relative; overflow: hidden; margin-top: -3px; border: 5px solid #86d9bd; border-radius: 23px 23px 38px 38px; }.flask > b::before { content: ''; position: absolute; inset: 38px -12px -8px; background: #60c6a4; border-radius: 50% 50% 0 0; opacity: .75; }.flask em { width: 7px; height: 7px; position: absolute; z-index: 1; background: #d8f4e9; border-radius: 50%; }.flask em:nth-child(1) { left: 21px; bottom: 18px; }.flask em:nth-child(2) { right: 23px; bottom: 34px; }.flask em:nth-child(3) { right: 16px; bottom: 13px; }.spark { position: absolute; color: var(--mint); }.spark-one { right: 58px; bottom: 238px; font-size: 22px; }.spark-two { right: 277px; bottom: 92px; font-size: 24px; }.panel-footer { position: relative; z-index: 2; color: #668b89; font-size: 10px; letter-spacing: .7px; }
.login-form-panel { min-height: 100vh; display: grid; place-items: center; padding: 48px; }.login-card { width: min(100%, 430px); }.mobile-brand { display: none; color: var(--mint-dark); font-family: Georgia, serif; font-size: 20px; font-weight: 700; }.login-card h2 { color: var(--ink); font-family: Georgia, 'Noto Serif SC', serif; font-size: 34px; font-weight: 600; }.form-intro { margin: 8px 0 34px; color: var(--muted); font-size: 13px; }.login-card :deep(.el-form-item) { margin-bottom: 24px; }.login-card :deep(.el-form-item__label) { padding-bottom: 8px; color: #345452; font-size: 12px; font-weight: 700; }.login-card :deep(.el-input__wrapper) { min-height: 49px; padding: 0 15px; background: #fff; border-radius: 11px; box-shadow: 0 0 0 1px #dfe3dc inset !important; }.login-card :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--mint-dark) inset, 0 6px 18px rgba(40, 123, 112, .07) !important; }.login-card :deep(.el-input__prefix) { color: #7b918e; font-size: 17px; }.login-button { width: 100%; height: 50px; margin-top: 5px; border-radius: 11px; box-shadow: 0 10px 22px rgba(40, 123, 112, .18); }.login-button .el-icon { margin-left: 5px; }.register-entry { margin-top: 24px; text-align: center; color: #7d8b89; font-size: 12px; }.register-entry a { color: var(--mint-dark); font-weight: 700; text-decoration: none; }.register-entry a:hover { text-decoration: underline; }
.support-text { display: flex; align-items: center; justify-content: center; gap: 5px; margin-top: 14px; color: #95a19e; font-size: 10px; }
@media (max-width: 850px) { .login-page { grid-template-columns: 1fr; }.login-brand-panel { display: none; }.login-form-panel { padding: 34px 22px; }.mobile-brand { display: block; margin-bottom: 30px; }.login-card h2 { font-size: 30px; } }
</style>
