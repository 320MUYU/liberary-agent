# 阅见 · 图书馆学习空间预约系统

阅见是一套面向高校图书馆的学习空间预约系统。读者可以查询研讨室、自习室和多媒体空间，提交分时预约并跟踪审核结果；管理员可以维护空间、配套设施、读者账号和预约申请。

## 技术栈

- 前端：Vue 3、Vite、Vue Router、Element Plus、Axios
- 后端：FastAPI、SQLAlchemy、MySQL、JWT、bcrypt
- AI 对话：LangChain、DeepSeek

项目为了兼容既有数据库，后端内部继续使用 `Lab`、`Equipment`、`lab_id` 与 `/api/lab` 等名称；产品界面统一使用“学习空间”和“设施”。

## 已实现功能

- 注册、登录、JWT 鉴权和读者资料维护
- 学习空间查询、筛选、封面和设施展示
- 空间预约、容量校验、时段冲突检查和取消规则
- 管理员维护读者、空间、设施并审核预约
- DeepSeek 多轮对话与预约规则提示
- 桌面端、平板和移动端响应式界面

## AI 能力边界与后续计划

当前只完成通用大模型对话接入，尚未实现 RAG。AI 无法读取馆规知识库、实时空间、设施或预约数据，也不能替读者执行预约。

后续 RAG 工作建议按以下顺序实施：

1. 整理馆规、预约规则和常见问题文档。
2. 建立文档切分、向量索引与增量更新流程。
3. 为检索结果增加来源引用和无结果兜底。
4. 将实时空间查询作为受控工具接入，与知识库检索分开。
5. 建立命中率、引用准确率和越权回答测试集。

## 本地运行

后端：

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

前端：

```powershell
cd vue-project
npm install
npm run dev
```

前端默认请求 `http://127.0.0.1:8000`，可在 `vue-project/.env.development` 中调整。

## 验证

```powershell
cd vue-project
npm run build

cd ..\backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

新数据库可以在 `backend` 目录运行 `scripts/seed.py` 创建管理员和图书馆演示空间。`scripts/convert_demo_labs.py` 只用于转换项目旧版官方演示数据，不会自动执行。
