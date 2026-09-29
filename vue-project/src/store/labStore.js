import { reactive } from 'vue'
import { getLabListApi } from '../labApi.js'

// 实验室数据现在来自后端（这里原来是写死的 6 条假数据）。
// 仍然导出成 reactive 数组，是因为 LabsView / DashboardView / BookingDialog
// 都直接遍历它渲染，保持这个形状可以让这些页面少改。
export const labs = reactive([])

let pending = null

// 拉取实验室列表。多个页面同时挂载会一起调它，共用一个请求，不会重复打接口。
// force=true 用于管理员改完数据后强制刷新。
export function loadLabs(force = false) {
  if (pending) return pending

  if (labs.length && !force) return Promise.resolve(labs)

  pending = getLabListApi()
    .then((list) => {
      // 用 splice 就地替换，而不是 labs.value = ...：保持对外暴露的
      // 还是同一个数组对象，已经引用了它的组件不会失联
      labs.splice(0, labs.length, ...list)
      return labs
    })
    .finally(() => {
      pending = null
    })

  return pending
}

// 卡片配色和图标按"类别"给。这类纯展示的取色不该存进数据库让管理员填，
// 所以从原来每条数据里挪到了这里，统一按类别映射。
const LAB_CATEGORY_STYLE = {
  人工智能: { color: '#dceee8', accent: '#387d70' },
  网络安全: { color: '#e7e9f2', accent: '#59658f' },
  嵌入式: { color: '#f3e8d7', accent: '#9b7440' },
  数字媒体: { color: '#f1dfde', accent: '#a75f5b' },
  云计算: { color: '#e1e9ed', accent: '#527488' },
  大数据: { color: '#e2eddd', accent: '#638754' },
}

const LAB_CATEGORY_ICON = {
  人工智能: 'DataAnalysis',
  网络安全: 'Lock',
  嵌入式: 'Cpu',
  数字媒体: 'VideoCamera',
  云计算: 'Cloudy',
  大数据: 'Histogram',
}

// 新类别（管理员自己加的）取不到预设值时给一套中性配色，不至于渲染成空白
export function labStyle(category) {
  return LAB_CATEGORY_STYLE[category] || { color: '#eaf0ee', accent: '#54807a' }
}

export function labIcon(category) {
  return LAB_CATEGORY_ICON[category] || 'Histogram'
}

// 设备台数：按数量累加，不是按"设备种类"数
export function labUnitCount(lab) {
  return (lab.equipments || []).reduce((sum, item) => sum + item.total, 0)
}

// 设备完好率 = 状态正常的设备种类 / 全部设备种类。
// 这是从真实设备数据算出来的，替换掉了原来手写的"利用率 68%"那种假数字。
export function labHealthyRate(lab) {
  const list = lab.equipments || []
  if (!list.length) return 0
  return Math.round((list.filter(isEquipmentHealthy).length / list.length) * 100)
}

// 全部实验室的整体设备完好率，给页面顶部的统计用
export function overallHealthyRate(list = labs) {
  const all = list.flatMap((lab) => lab.equipments || [])
  if (!all.length) return 0
  return Math.round((all.filter(isEquipmentHealthy).length / all.length) * 100)
}

const defaultBookings = [
  { id: 1001, labId: 1, lab: '智能感知实验室', room: 'A-301', date: '2026-09-22', start: '14:00', end: '16:00', purpose: '计算机视觉课程实验', people: 4, status: 'approved', createdAt: '2026-09-19' },
  { id: 1002, labId: 3, lab: '嵌入式系统实验室', room: 'C-205', date: '2026-09-24', start: '09:00', end: '11:00', purpose: '物联网课程小组实验', people: 6, status: 'pending', createdAt: '2026-09-21' },
  { id: 1003, labId: 4, lab: '数字媒体实验室', room: 'D-602', date: '2026-09-17', start: '13:00', end: '15:00', purpose: 'VR 交互项目测试', people: 3, status: 'completed', createdAt: '2026-09-15' },
]

function loadBookings() {
  try { return JSON.parse(localStorage.getItem('labmind-bookings')) || defaultBookings } catch { return defaultBookings }
}

export const bookings = reactive(loadBookings())
export const notifications = reactive([
  { id: 1, title: '预约审核通过', content: '智能感知实验室的预约已通过审核。', time: '10 分钟前', type: 'success' },
  { id: 2, title: '实验即将开始', content: '请在 13:50 前往 A-301 签到。', time: '1 小时前', type: 'warning' },
])

function persist() { localStorage.setItem('labmind-bookings', JSON.stringify(bookings)) }

export function addBooking(data) {
  const lab = labs.find((item) => item.id === Number(data.labId))
  const booking = { id: Date.now(), labId: lab.id, lab: lab.name, room: lab.code, status: 'pending', createdAt: new Date().toISOString().slice(0, 10), ...data }
  bookings.unshift(booking)
  persist()
  return booking
}

export function cancelBooking(id) {
  const booking = bookings.find((item) => item.id === id)
  if (booking) booking.status = 'cancelled'
  persist()
}

export const statusMap = {
  approved: { label: '已通过', class: '' }, pending: { label: '审核中', class: 'pending' },
  completed: { label: '已完成', class: 'completed' }, cancelled: { label: '已取消', class: 'cancelled' },
}

export const labStatusMap = {
  available: { label: '可预约', type: 'success' }, busy: { label: '使用中', type: 'warning' }, maintenance: { label: '维护中', type: 'info' },
}

// 设备状态：取值与后端 EquipmentCreateRequest 的 Literal 一一对应
export const equipmentStatusMap = {
  normal: { label: '正常', type: 'success' },
  repair: { label: '维修中', type: 'warning' },
  scrapped: { label: '已报废', type: 'danger' },
}

// "算不算完好"只在这里定义一次，下面两个完好率函数都走它，
// 免得以后加状态时改漏一处
export function isEquipmentHealthy(equipment) {
  return equipment.status === 'normal'
}
