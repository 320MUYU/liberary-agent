# LabMind 智能实验室预约前端

基于 Vue 3、Vite、Vue Router 与 Element Plus 实现的智能实验室预约系统前端。

## 已实现页面

- 工作台：实验室概况、近期预约、使用统计与智能推荐
- 实验室资源：搜索、分类筛选、状态筛选、设备信息与预约入口
- 我的预约：状态统计、记录筛选、取消预约与新建预约
- AI 智能助理：需求对话、RAG 来源展示、Agent 执行轨迹与推荐结果
- 预约弹窗：实验室、日期、时间、人数、用途及补充说明
- 桌面端与移动端响应式布局

## 运行项目

```bash
npm install
npm run dev
```

生产构建：

```bash
npm run build
```

## 数据说明

当前仓库只实现前端。实验室数据、预约数据和 AI 回复位于 `src/store/labStore.js` 及前端页面中，预约记录会写入浏览器 `localStorage`，方便在没有后端时完整演示业务流程。

接入 FastAPI 后，可将 `src/store/labStore.js` 中的本地数据操作替换为真实 HTTP API；AI 页面当前展示的 RAG、Tool Calling 与 LangGraph 流程均为前端交互演示，不包含后端模型调用。
