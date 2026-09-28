<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { registerApi } from '@/authApi'

const router = useRouter()
const formRef = ref()
const loading = ref(false)
const form = reactive({
  username: '',
  name: '',
  password: '',
  confirm_password: '',
})

// 确认密码的校验函数：Element Plus 的 rule 支持自定义 validator，
// 参数固定是 (rule, value, callback)，校验不通过就 callback(new Error('提示'))
function validateConfirmPassword(rule, value, callback) {
  if (!value) {
    callback(new Error('请再次输入密码'))
    return
  }

  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
    return
  }

  callback()
}

// 这里的规则和账号、密码的限制，与后端 RegisterRequest 保持一致。
// 前端校验只是为了少发一次请求、提示更即时，不能替代后端校验
// （请求可以绕过浏览器直接发，后端才是最终防线）
const rules = {
  username: [
    { required: true, message: '请输入账号', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9_]{3,20}$/,
      message: '账号只能包含字母、数字、下划线，长度 3-20 位',
      trigger: 'blur',
    },
  ],
  name: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { max: 50, message: '姓名长度不能超过 50 位', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度需为 6-32 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

async function register() {
  if (loading.value) return

  const valid = await formRef.value.validate().catch(() => false)

  if (!valid) return

  loading.value = true

  try {
    const user = await registerApi(form)
    ElMessage.success('注册成功，请使用新账号登录')
    // 注册接口不返回 token，所以这里跳回登录页手动登录；
    // 顺手把账号通过 query 带过去，登录页可以自动填好账号
    await router.replace({
      name: 'login',
      query: { username: user?.username || form.username },
    })
  } catch {
    // 请求错误由 Axios 响应拦截器统一提示。
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="register-page">
    <section class="register-brand-panel">
      <div class="brand-lockup">
        <span class="brand-mark"><span></span><span></span><span></span></span>
        <div><strong>LabMind</strong><small>智能实验室预约平台</small></div>
      </div>

      <div class="brand-copy">
        <span class="eyebrow">CREATE ACCOUNT</span>
        <h1>注册一个账号<br />开启你的实验计划</h1>
        <p>注册后即可查询实验室资源、提交预约申请，并使用 AI 智能助理帮你匹配空闲时段。</p>
      </div>

      <div class="lab-visual" aria-hidden="true">
        <span class="orbit orbit-one"></span>
        <span class="orbit orbit-two"></span>
        <span class="flask"><i></i><b><em></em><em></em><em></em></b></span>
        <span class="spark spark-one">✦</span>
        <span class="spark spark-two">＋</span>
      </div>

      <p class="panel-footer">课程设计 · LabMind v1.0</p>
    </section>

    <section class="register-form-panel">
      <div class="register-card">
        <span class="mobile-brand">LabMind</span>
        <h2>创建账号</h2>
        <p class="form-intro">填写以下信息完成注册，注册后返回登录</p>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="register">
          <el-form-item label="账号" prop="username">
            <el-input v-model="form.username" size="large" autocomplete="username" placeholder="3-20 位字母、数字或下划线">
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>

          <el-form-item label="姓名" prop="name">
            <el-input v-model="form.name" size="large" autocomplete="name" placeholder="请输入真实姓名">
              <template #prefix><el-icon><Postcard /></el-icon></template>
            </el-input>
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" size="large" type="password" show-password autocomplete="new-password" placeholder="6-32 位密码">
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>

          <el-form-item label="确认密码" prop="confirm_password">
            <el-input v-model="form.confirm_password" size="large" type="password" show-password autocomplete="new-password" placeholder="请再次输入密码">
              <template #prefix><el-icon><Key /></el-icon></template>
            </el-input>
          </el-form-item>

          <el-button class="register-button" type="primary" size="large" :loading="loading" @click="register">
            注册账号 <el-icon v-if="!loading"><Right /></el-icon>
          </el-button>
        </el-form>

        <p class="support-text">
          已有账号？<router-link :to="{ name: 'login' }">返回登录</router-link>
        </p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.register-page { min-height: 100vh; display: grid; grid-template-columns: minmax(420px, 1.05fr) minmax(420px, .95fr); background: #f8f7f3; }
.register-brand-panel { min-height: 100vh; display: flex; flex-direction: column; position: relative; overflow: hidden; padding: 46px 58px 34px; color: white; background: #123b3a; }
.register-brand-panel::before { content: ''; position: absolute; inset: 0; background: radial-gradient(circle at 78% 70%, rgba(126, 215, 185, .18), transparent 37%), linear-gradient(145deg, rgba(255,255,255,.025), transparent 45%); }
.brand-lockup { display: flex; align-items: center; gap: 13px; position: relative; z-index: 2; }.brand-lockup strong { display: block; font-family: Georgia, serif; font-size: 24px; letter-spacing: .4px; }.brand-lockup small { display: block; margin-top: 1px; color: #91afad; font-size: 10px; letter-spacing: .9px; }
.brand-mark { width: 42px; height: 42px; display: flex; align-items: end; justify-content: center; gap: 3px; padding: 9px; border-radius: 13px; background: var(--mint); transform: rotate(-2deg); }.brand-mark span { width: 5px; display: block; background: #143c3b; border-radius: 5px 5px 2px 2px; }.brand-mark span:nth-child(1) { height: 12px; }.brand-mark span:nth-child(2) { height: 22px; }.brand-mark span:nth-child(3) { height: 16px; }
.brand-copy { max-width: 590px; position: relative; z-index: 2; margin: auto 0; padding-bottom: 82px; }.eyebrow { color: #87cbb5; font-size: 10px; font-weight: 800; letter-spacing: 2.7px; }.brand-copy h1 { margin-top: 22px; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(38px, 4vw, 61px); font-weight: 500; line-height: 1.22; letter-spacing: 1px; }.brand-copy p { max-width: 480px; margin-top: 24px; color: #a9c2c0; font-size: 14px; line-height: 1.9; }
.lab-visual { width: 360px; height: 360px; position: absolute; right: -30px; bottom: -42px; opacity: .72; }.orbit { position: absolute; border: 1px solid rgba(148, 222, 198, .2); border-radius: 50%; }.orbit-one { width: 330px; height: 330px; right: -10px; bottom: -10px; }.orbit-two { width: 220px; height: 220px; right: 45px; bottom: 45px; }.flask { width: 94px; height: 150px; position: absolute; right: 118px; bottom: 100px; }.flask > i { width: 31px; height: 52px; display: block; margin: auto; border: 5px solid #86d9bd; border-width: 0 5px; }.flask > b { width: 94px; height: 94px; display: block; position: relative; overflow: hidden; margin-top: -3px; border: 5px solid #86d9bd; border-radius: 23px 23px 38px 38px; }.flask > b::before { content: ''; position: absolute; inset: 38px -12px -8px; background: #60c6a4; border-radius: 50% 50% 0 0; opacity: .75; }.flask em { width: 7px; height: 7px; position: absolute; z-index: 1; background: #d8f4e9; border-radius: 50%; }.flask em:nth-child(1) { left: 21px; bottom: 18px; }.flask em:nth-child(2) { right: 23px; bottom: 34px; }.flask em:nth-child(3) { right: 16px; bottom: 13px; }.spark { position: absolute; color: var(--mint); }.spark-one { right: 58px; bottom: 238px; font-size: 22px; }.spark-two { right: 277px; bottom: 92px; font-size: 24px; }.panel-footer { position: relative; z-index: 2; color: #668b89; font-size: 10px; letter-spacing: .7px; }
.register-form-panel { min-height: 100vh; display: grid; place-items: center; padding: 42px 48px; }.register-card { width: min(100%, 430px); }.mobile-brand { display: none; color: var(--mint-dark); font-family: Georgia, serif; font-size: 20px; font-weight: 700; }.register-card h2 { color: var(--ink); font-family: Georgia, 'Noto Serif SC', serif; font-size: 34px; font-weight: 600; }.form-intro { margin: 8px 0 30px; color: var(--muted); font-size: 13px; }.register-card :deep(.el-form-item) { margin-bottom: 19px; }.register-card :deep(.el-form-item__label) { padding-bottom: 7px; color: #345452; font-size: 12px; font-weight: 700; }.register-card :deep(.el-input__wrapper) { min-height: 47px; padding: 0 15px; background: #fff; border-radius: 11px; box-shadow: 0 0 0 1px #dfe3dc inset !important; }.register-card :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--mint-dark) inset, 0 6px 18px rgba(40, 123, 112, .07) !important; }.register-card :deep(.el-input__prefix) { color: #7b918e; font-size: 17px; }.register-button { width: 100%; height: 50px; margin-top: 8px; border-radius: 11px; box-shadow: 0 10px 22px rgba(40, 123, 112, .18); }.register-button .el-icon { margin-left: 5px; }.support-text { margin-top: 22px; text-align: center; color: #95a19e; font-size: 12px; }.support-text a { color: var(--mint-dark); font-weight: 700; text-decoration: none; }.support-text a:hover { text-decoration: underline; }
@media (max-width: 850px) { .register-page { grid-template-columns: 1fr; }.register-brand-panel { display: none; }.register-form-panel { padding: 34px 22px; }.mobile-brand { display: block; margin-bottom: 26px; }.register-card h2 { font-size: 30px; } }
</style>
