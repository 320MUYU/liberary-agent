<script setup>
import { computed } from 'vue'
import { BRAND } from '@/config/brand'

const props = defineProps({ mode: { type: String, default: 'login' } })
const isRegister = computed(() => props.mode === 'register')
</script>

<template>
  <section class="auth-brand-panel">
    <div class="brand-lockup">
      <span class="brand-mark" aria-hidden="true"><i></i><i></i></span>
      <div><strong>{{ BRAND.name }}</strong><small>{{ BRAND.englishName }}</small></div>
    </div>
    <div class="brand-copy">
      <span class="eyebrow">LIBRARY SPACE RESERVATION</span>
      <h1 v-if="isRegister">加入阅见<br />让好时光有处安放</h1>
      <h1 v-else>为下一次阅读<br />预留一方安静</h1>
      <p v-if="isRegister">创建读者账号，在线查看学习空间、提交预约并跟踪审核进度。</p>
      <p v-else>连接图书馆里的每一处安静空间，让阅读、讨论与灵感都能准时发生。</p>
    </div>
    <div class="library-visual" aria-hidden="true">
      <span class="window"></span>
      <span class="lamp"><i></i><b></b></span>
      <span class="shelf"><i></i><i></i><i></i><i></i><i></i><i></i></span>
      <span class="table"></span>
      <span class="book book-one"></span><span class="book book-two"></span>
    </div>
    <p class="panel-footer">{{ BRAND.fullName }} · v1.0</p>
  </section>
</template>

<style scoped>
.auth-brand-panel { min-height: 100vh; display: flex; flex-direction: column; position: relative; overflow: hidden; padding: 46px 58px 34px; color: #fff; background: var(--navy-900); }
.auth-brand-panel::before { content: ''; position: absolute; inset: 0; background: radial-gradient(circle at 77% 70%, rgba(201,148,60,.18), transparent 34%), linear-gradient(145deg, rgba(255,255,255,.04), transparent 45%); }
.brand-lockup { display: flex; align-items: center; gap: 13px; position: relative; z-index: 2; }
.brand-lockup strong { display: block; color: #fff; font-family: 'Songti SC', SimSun, serif; font-size: 28px; letter-spacing: 4px; }
.brand-lockup small { display: block; margin-top: 1px; color: #b6c1ca; font-size: 9px; font-weight: 700; letter-spacing: 2.2px; }
.brand-mark { width: 43px; height: 43px; display: flex; position: relative; padding: 10px 8px 8px; background: var(--gold-500); border-radius: 12px; }
.brand-mark i { width: 50%; height: 24px; display: block; background: #fffefa; }
.brand-mark i:first-child { border-radius: 3px 0 8px 3px; transform: skewY(8deg); transform-origin: right bottom; }
.brand-mark i:last-child { border-radius: 0 3px 3px 8px; transform: skewY(-8deg); transform-origin: left bottom; }
.brand-mark::after { content: ''; width: 2px; height: 23px; position: absolute; left: 50%; top: 10px; background: var(--gold-700); transform: translateX(-50%); }
.brand-copy { max-width: 600px; position: relative; z-index: 2; margin: auto 0; padding-bottom: 74px; }
.eyebrow { color: #e5be78; font-size: 10px; font-weight: 800; letter-spacing: 2.7px; }
.brand-copy h1 { margin-top: 22px; color: #fffefa; font-size: clamp(40px, 4vw, 62px); font-weight: 500; line-height: 1.22; letter-spacing: 2px; }
.brand-copy p { max-width: 480px; margin-top: 24px; color: #c6d0d8; font-size: 14px; line-height: 1.9; }
.library-visual { width: 430px; height: 330px; position: absolute; right: -34px; bottom: 0; opacity: .82; }
.window { width: 190px; height: 190px; position: absolute; right: 55px; bottom: 112px; border: 2px solid rgba(245,234,214,.32); border-radius: 95px 95px 0 0; }
.window::before, .window::after { content: ''; position: absolute; background: rgba(245,234,214,.22); }
.window::before { width: 2px; inset: 0 auto 0 50%; }.window::after { height: 2px; inset: 54% 0 auto; }
.lamp { position: absolute; right: 258px; bottom: 77px; }
.lamp i { width: 64px; height: 34px; display: block; background: #d4a653; clip-path: polygon(24% 0,76% 0,100% 100%,0 100%); border-radius: 8px 8px 3px 3px; }
.lamp b { width: 5px; height: 92px; display: block; margin: auto; background: #bdc9d2; }
.lamp b::after { content: ''; width: 60px; height: 5px; display: block; position: relative; left: -27px; top: 88px; background: #bdc9d2; border-radius: 6px; }
.shelf { width: 132px; height: 108px; display: flex; align-items: end; gap: 6px; position: absolute; right: 37px; bottom: 44px; padding: 0 12px 10px; border-bottom: 7px solid #d9c399; }
.shelf i { width: 13px; display: block; background: #f3e9d7; border-radius: 2px 2px 0 0; }
.shelf i:nth-child(1) { height: 70px; background: #c9923f; }.shelf i:nth-child(2) { height: 84px; }.shelf i:nth-child(3) { height: 62px; background: #8ba1b2; }.shelf i:nth-child(4) { height: 90px; }.shelf i:nth-child(5) { height: 73px; background: #c9923f; }.shelf i:nth-child(6) { height: 80px; background: #8ba1b2; }
.table { width: 310px; height: 7px; position: absolute; right: 26px; bottom: 72px; background: #9eb0bd; border-radius: 5px; }
.table::before, .table::after { content: ''; width: 7px; height: 70px; position: absolute; top: 5px; background: #9eb0bd; }.table::before { left: 28px; }.table::after { right: 28px; }
.book { height: 10px; position: absolute; bottom: 80px; background: #e5be78; border-radius: 2px; }.book-one { width: 58px; right: 102px; }.book-two { width: 45px; right: 109px; bottom: 90px; background: #dfe7ec; }
.panel-footer { position: relative; z-index: 2; color: #8599a8; font-size: 10px; letter-spacing: .6px; }
@media (max-width: 850px) { .auth-brand-panel { display: none; } }
</style>
