<script setup>
import { computed, ref } from 'vue'
import BookingDialog from '@/components/BookingDialog.vue'
import { labs, labStatusMap } from '@/store/labStore'

const search = ref('')
const category = ref('全部')
const status = ref('all')
const bookingOpen = ref(false)
const selectedLab = ref(null)
const categories = ['全部', ...new Set(labs.map((lab) => lab.category))]

const filteredLabs = computed(() => labs.filter((lab) => {
  const keyword = search.value.trim().toLowerCase()
  const matchText = !keyword || [lab.name, lab.code, lab.building, ...lab.equipment].join(' ').toLowerCase().includes(keyword)
  return matchText && (category.value === '全部' || lab.category === category.value) && (status.value === 'all' || lab.status === status.value)
}))

function openBooking(lab) { selectedLab.value = lab; bookingOpen.value = true }
function resetFilters() { search.value = ''; category.value = '全部'; status.value = 'all' }
</script>

<template>
  <div class="labs-page">
    <section class="resource-intro">
      <div><span>LABORATORY DIRECTORY</span><h2>找到适合你的实验空间</h2><p>查看实验室设备、容量与当前开放状态，选择后即可在线提交预约。</p></div>
      <div class="intro-numbers"><div><strong>{{ labs.length }}</strong><span>实验室总数</span></div><i></i><div><strong>{{ labs.filter(l => l.status === 'available').length }}</strong><span>当前可预约</span></div><i></i><div><strong>98%</strong><span>设备完好率</span></div></div>
    </section>

    <section class="filter-bar surface">
      <el-input v-model="search" clearable placeholder="搜索名称、位置或设备" class="search-input"><template #prefix><el-icon><Search /></el-icon></template></el-input>
      <el-select v-model="category" class="filter-select"><el-option v-for="item in categories" :key="item" :label="item === '全部' ? '全部类别' : item" :value="item" /></el-select>
      <el-select v-model="status" class="filter-select"><el-option label="全部状态" value="all"/><el-option label="可预约" value="available"/><el-option label="使用中" value="busy"/><el-option label="维护中" value="maintenance"/></el-select>
      <div class="result-count">找到 <strong>{{ filteredLabs.length }}</strong> 间实验室</div>
    </section>

    <div v-if="filteredLabs.length" class="lab-grid">
      <article v-for="lab in filteredLabs" :key="lab.id" class="lab-card surface">
        <div class="card-visual" :style="{ background: lab.color, color: lab.accent }">
          <span class="category-tag">{{ lab.category }}</span>
          <el-icon class="visual-icon"><DataAnalysis v-if="lab.category === '人工智能'"/><Lock v-else-if="lab.category === '网络安全'"/><Cpu v-else-if="lab.category === '嵌入式'"/><VideoCamera v-else-if="lab.category === '数字媒体'"/><Cloudy v-else-if="lab.category === '云计算'"/><Histogram v-else/></el-icon>
          <div class="line-art"><i></i><i></i><i></i></div>
        </div>
        <div class="card-content">
          <div class="card-title"><div><small>{{ lab.code }}</small><h3>{{ lab.name }}</h3></div><el-tag :type="labStatusMap[lab.status].type" effect="light" size="small">{{ labStatusMap[lab.status].label }}</el-tag></div>
          <p class="description">{{ lab.description }}</p>
          <div class="meta-row"><span><el-icon><Location /></el-icon>{{ lab.building }} · {{ lab.floor }}</span><span><el-icon><User /></el-icon>{{ lab.capacity }} 人</span></div>
          <div class="equipment"><span v-for="item in lab.equipment" :key="item">{{ item }}</span></div>
          <div class="availability"><div><small>最近空闲</small><strong>{{ lab.nextFree }}</strong></div><div v-if="lab.status !== 'maintenance'" class="usage"><span><i :style="{ width: `${lab.occupied}%` }"></i></span><small>利用率 {{ lab.occupied }}%</small></div></div>
          <el-button :disabled="lab.status === 'maintenance'" :type="lab.status === 'available' ? 'primary' : 'default'" class="book-button" @click="openBooking(lab)">{{ lab.status === 'maintenance' ? '暂不开放' : '选择该实验室' }}<el-icon><Right /></el-icon></el-button>
        </div>
      </article>
    </div>
    <div v-else class="empty-state surface"><span><el-icon><Search /></el-icon></span><h3>没有找到匹配的实验室</h3><p>换个关键词或清除筛选条件试试</p><el-button @click="resetFilters">清除筛选</el-button></div>

    <BookingDialog v-model="bookingOpen" :selected-lab="selectedLab" />
  </div>
</template>

<style scoped>
.resource-intro { min-height: 142px; display: flex; align-items: center; justify-content: space-between; gap: 25px; margin-bottom: 20px; padding: 26px 32px; overflow: hidden; position: relative; color: white; background: #1d5552; border-radius: 17px; }.resource-intro::after { content: ''; position: absolute; right: -45px; top: -105px; width: 260px; height: 260px; border: 1px solid rgba(126,215,185,.18); border-radius: 50%; }.resource-intro > div { position: relative; z-index: 1; }.resource-intro > div:first-child span { color: #81c9b3; font-size: 8px; font-weight: 800; letter-spacing: 1.8px; }.resource-intro h2 { margin-top: 8px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; font-weight: 600; }.resource-intro p { margin-top: 7px; color: #abc7c3; font-size: 11px; }.intro-numbers { display: flex; align-items: center; gap: 25px; margin-right: 18px; }.intro-numbers div { text-align: center; }.intro-numbers strong, .intro-numbers span { display: block; }.intro-numbers strong { color: #a4e5cf; font-family: Georgia, serif; font-size: 24px; }.intro-numbers span { margin-top: 2px; color: #9bbab6; font-size: 8px; }.intro-numbers i { width: 1px; height: 34px; background: rgba(255,255,255,.13); }
.filter-bar { display: flex; align-items: center; gap: 11px; margin-bottom: 20px; padding: 14px; }.search-input { width: min(360px, 40%); }.filter-select { width: 140px; }.result-count { margin-left: auto; color: #889693; font-size: 10px; }.result-count strong { color: var(--mint-dark); }.lab-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }.lab-card { overflow: hidden; transition: transform .2s, box-shadow .2s; }.lab-card:hover { transform: translateY(-3px); box-shadow: 0 14px 30px rgba(32,73,70,.08); }.card-visual { height: 118px; display: grid; place-items: center; position: relative; overflow: hidden; }.category-tag { position: absolute; left: 15px; top: 14px; padding: 4px 8px; font-size: 8px; font-weight: 700; background: rgba(255,255,255,.6); border-radius: 5px; }.visual-icon { font-size: 42px; opacity: .8; }.line-art i { position: absolute; border: 1px solid currentColor; border-radius: 50%; opacity: .12; }.line-art i:nth-child(1) { width: 110px; height: 110px; left: -30px; top: -50px; }.line-art i:nth-child(2) { width: 80px; height: 80px; right: -20px; bottom: -35px; }.line-art i:nth-child(3) { width: 30px; height: 30px; right: 35px; top: 15px; }.card-content { padding: 17px; }.card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; }.card-title small { color: #97a39f; font-size: 8px; letter-spacing: .7px; }.card-title h3 { margin-top: 2px; color: var(--ink); font-size: 14px; }.description { height: 36px; overflow: hidden; margin-top: 10px; color: #778783; font-size: 10px; line-height: 1.7; }.meta-row { display: flex; gap: 16px; margin-top: 12px; color: #81908d; font-size: 9px; }.meta-row span { display: flex; align-items: center; gap: 4px; }.equipment { min-height: 49px; display: flex; flex-wrap: wrap; align-content: start; gap: 5px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #ecece7; }.equipment span { height: fit-content; padding: 3px 7px; color: #617a76; font-size: 8px; background: #f0f5f2; border-radius: 5px; }.availability { min-height: 42px; display: flex; justify-content: space-between; align-items: center; }.availability small { display: block; color: #97a29f; font-size: 8px; }.availability strong { display: block; margin-top: 2px; color: #355a56; font-size: 10px; }.usage { width: 90px; text-align: right; }.usage > span { width: 72px; height: 4px; display: inline-block; overflow: hidden; background: #edf0eb; border-radius: 5px; }.usage > span i { height: 100%; display: block; background: #76c8ac; border-radius: 5px; }.book-button { width: 100%; margin-top: 11px; }.empty-state { padding: 70px 20px; text-align: center; }.empty-state > span { width: 55px; height: 55px; display: grid; place-items: center; margin: auto; color: #78918d; font-size: 23px; background: #eef4f1; border-radius: 15px; }.empty-state h3 { margin-top: 14px; color: var(--ink); }.empty-state p { margin: 5px 0 17px; color: #8a9794; font-size: 11px; }
@media (max-width: 1150px) { .lab-grid { grid-template-columns: repeat(2, 1fr); }.intro-numbers { gap: 14px; } }
@media (max-width: 700px) { .resource-intro { align-items: start; flex-direction: column; padding: 24px; }.intro-numbers { width: 100%; justify-content: space-between; margin: 5px 0 0; }.filter-bar { flex-wrap: wrap; }.search-input { width: 100%; }.filter-select { flex: 1; }.result-count { width: 100%; margin: 0; }.lab-grid { grid-template-columns: 1fr; } }
</style>
