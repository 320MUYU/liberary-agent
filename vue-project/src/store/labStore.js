import { reactive } from 'vue'

export const labs = reactive([
  { id: 1, name: '智能感知实验室', code: 'A-301', building: '信息楼 A区', floor: '3F', capacity: 24, category: '人工智能', status: 'available', nextFree: '今日 14:00', color: '#dceee8', accent: '#387d70', equipment: ['GPU 工作站', '机器视觉平台', '边缘计算盒'], description: '面向机器视觉、深度学习和智能感知实验，配备高性能 GPU 集群。', occupied: 68 },
  { id: 2, name: '网络安全实验室', code: 'B-408', building: '信息楼 B区', floor: '4F', capacity: 32, category: '网络安全', status: 'busy', nextFree: '明日 09:00', color: '#e7e9f2', accent: '#59658f', equipment: ['攻防靶场', '网络分析仪', '服务器集群'], description: '支持网络攻防、密码学和安全审计等综合实践教学。', occupied: 86 },
  { id: 3, name: '嵌入式系统实验室', code: 'C-205', building: '工程训练中心', floor: '2F', capacity: 20, category: '嵌入式', status: 'available', nextFree: '今日 16:00', color: '#f3e8d7', accent: '#9b7440', equipment: ['示波器', 'STM32 套件', '逻辑分析仪'], description: '提供嵌入式开发、物联网与电子系统设计所需的软硬件环境。', occupied: 52 },
  { id: 4, name: '数字媒体实验室', code: 'D-602', building: '创新中心', floor: '6F', capacity: 28, category: '数字媒体', status: 'available', nextFree: '今日 13:30', color: '#f1dfde', accent: '#a75f5b', equipment: ['动作捕捉', 'VR 头显', '图形工作站'], description: '适合虚拟现实、数字内容创作、人机交互与三维动画项目。', occupied: 37 },
  { id: 5, name: '云计算联合实验室', code: 'A-507', building: '信息楼 A区', floor: '5F', capacity: 36, category: '云计算', status: 'maintenance', nextFree: '9月25日', color: '#e1e9ed', accent: '#527488', equipment: ['云平台节点', '存储阵列', '高速交换机'], description: '部署私有云教学平台，满足分布式计算和云原生实践需求。', occupied: 0 },
  { id: 6, name: '大数据创新实验室', code: 'B-503', building: '信息楼 B区', floor: '5F', capacity: 40, category: '大数据', status: 'available', nextFree: '明日 10:00', color: '#e2eddd', accent: '#638754', equipment: ['Hadoop 集群', '数据大屏', '高性能服务器'], description: '支持数据采集、分布式处理、可视化和数据挖掘课程实践。', occupied: 74 },
])

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
