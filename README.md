# 阅见 · 图书馆学习空间预约系统

阅见是一套面向高校图书馆的学习空间预约系统。读者可以查询研讨室、自习室和多媒体空间，提交分时预约并跟踪审核结果；管理员可以维护空间、配套设施、读者账号和预约申请。

## 技术栈

- 前端：Vue 3、Vite、Vue Router、Element Plus、Axios
- 后端：FastAPI、SQLAlchemy、MySQL、JWT、bcrypt
- AI 对话：LangChain、DeepSeek；可选 RAG 使用硅基流动 `BAAI/bge-m3`、Chroma HTTP 服务（兼容百炼原生接口）

项目为了兼容既有数据库，后端内部继续使用 `Lab`、`Equipment`、`lab_id` 与 `/api/lab` 等名称；产品界面统一使用“学习空间”和“设施”。

## 已实现功能

- 注册、登录、JWT 鉴权和读者资料维护
- 学习空间查询、筛选、封面和设施展示
- 空间预约、容量校验、时段冲突检查和取消规则
- 管理员维护读者、空间、设施并审核预约
- DeepSeek 多轮对话、公开文档知识问答与来源引用
- 管理员知识文档上传、索引任务、版本发布、停用与失败重试
- 桌面端、平板和移动端响应式界面

## AI 能力边界

普通聊天默认可用，RAG 默认关闭。启用知识库后，管理员上传并发布的馆规、预约说明等静态文档可用于知识问答；每条回答附本轮来源，资料不足时拒绝编造。知识文档放在私有目录，不通过公开 `/uploads` 提供。

AI 当前不能读取实时空间、设施和个人预约数据，也不能替读者提交、审核或取消预约。数字引用有效不等于答案事实正确，上线前仍需用学校正式文档人工验收。仓库中的评估资料明确标为合成测试，不是学校馆规。

配置、启动顺序、文档发布和评估见 [RAG 使用与验收指南](docs/rag-guide.md)。

## 本地运行

首次准备后端（Python 3.13，先准备 MySQL）：

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

编辑 `backend/.env` 中的数据库、JWT 和 `DEEPSEEK_API_KEY` 后启动 API：

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

前端另开终端（Node 满足 `vue-project/package.json` 的 engines）：

```powershell
cd vue-project
npm install
npm run dev
```

前端默认请求 `http://127.0.0.1:8000`，可在 `vue-project/.env.development` 中调整。

启用 RAG 时，在本地 `.env` 设置 `RAG_ENABLED=true`、`EMBEDDING_PROVIDER=openai-compatible`、`EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1`、`EMBEDDING_MODEL=BAAI/bge-m3` 和独立 `EMBEDDING_API_KEY`，并额外启动两个常驻进程（各自终端均位于 `backend`）：

```powershell
.venv\Scripts\chroma.exe run --path .\data\chroma --host 127.0.0.1 --port 8001
```

```powershell
.venv\Scripts\python.exe knowledge_worker.py
```

API、Chroma 与 worker 需要同时运行；修改 `.env` 后重启 API 和 worker。Chroma 当前仅限本机无认证访问，勿直接暴露公网。DeepSeek 和嵌入服务的真实密钥只填本地 `.env`，不提交到 Git。

## 验证

```powershell
cd vue-project
npm run build

cd ..\backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/evaluate_rag.py
```

离线评估默认使用 30 条合成用例及假向量/假模型，输出命中、引用合法性、拒答与耗时指标，不调用云端，不代表真实检索质量。正式验收需人工建立真实文档评估集；`--live` 会真实调用服务并产生费用，参见指南。

新数据库可以在 `backend` 目录运行 `scripts/seed.py` 创建管理员和图书馆演示空间。`scripts/convert_demo_labs.py` 只用于转换项目旧版官方演示数据，不会自动执行。
