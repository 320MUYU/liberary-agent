# 阅见 · 图书借阅与学习空间预约系统

阅见是一套面向高校图书馆的实体图书借还与学习空间预约系统。读者可以检索图书、申请借阅和归还，也可以查询研讨室、自习室和多媒体空间并提交分时预约；管理员维护书目、馆藏副本、空间、设施和账号，确认实体书借出与归还并审核预约。第一版借期为30天，每人最多同时借阅5册，不含续借和罚款。

## 技术栈

- 前端：Vue 3、Vite、Vue Router、Element Plus、Axios
- 后端：FastAPI、SQLAlchemy、MySQL、JWT、bcrypt
- AI 对话：LangChain、DeepSeek；可选 RAG 使用 `BAAI/bge-m3`、Chroma、中文 BM25L 与 RRF 融合，可开关硅基流动 `BAAI/bge-reranker-v2-m3` 重排
- 借阅 Agent：LangGraph、SQLite 检查点、可选 MCP Streamable HTTP、确认与幂等回执

项目为了兼容既有数据库，后端内部继续使用 `Lab`、`Equipment`、`lab_id` 与 `/api/lab` 等名称；产品界面统一使用“学习空间”和“设施”。

## 已实现功能

- 注册、登录、JWT 鉴权和读者资料维护
- 图书检索、详情与实际馆藏库存展示
- 读者申请借阅、取消待确认借出申请、申请归还和查看借阅历史
- 管理员维护书目及副本、上下架、拒绝申请、确认借出和确认归还
- 学习空间查询、筛选、封面和设施展示
- 空间预约、容量校验、时段冲突检查和取消规则
- 管理员维护读者、空间、设施并审核预约
- DeepSeek 多轮对话、公开文档知识问答与来源引用
- 管理员知识文档上传、索引任务、版本发布、停用与失败重试
- 管理员对比向量、混合及重排检索，查看召回原文与实际 Chroma 入库记录
- 图书借阅助手：自然语言找书、选择书目、确认申请与刷新恢复
- 桌面端、平板和移动端响应式界面

## AI 能力边界

普通聊天默认可用，RAG 默认关闭。启用知识库后，管理员上传并发布的馆规、预约说明等静态文档可用于知识问答；每条回答附本轮来源，资料不足时拒绝编造。知识文档放在私有目录，不通过公开 `/uploads` 提供。

“图书借阅助手”模式可以查询真实书目和库存，用户选择具体书目并确认后提交借阅申请，仍需管理员确认借出；包含 LangGraph、MCP 工具接入与基础 Harness。普通聊天和知识库模式不执行业务操作；Agent 尚未接入归还、空间预约、管理员审批或多 Agent。数字引用有效不等于答案事实正确，上线前仍需用学校正式文档人工验收。仓库中的评估资料明确标为合成测试，不是学校馆规。

新增服务的启动方式、确认流程及恢复说明见 [Agent 使用与验收指南](docs/agent-guide.md)。MCP 模式下，借阅助手需要 Vue、FastAPI、MCP 三个进程；完整 RAG 再加 Chroma 和索引 worker。LangGraph 随 API 运行，Harness 按需测试，无须另起常驻进程。

配置、启动顺序、文档发布和评估见 [RAG 使用与验收指南](docs/rag-guide.md)。

检索支持保留原问题与追问改写、中文关键词和向量双路召回、RRF 融合、去重、可选模型重排与相邻切片补全。重排失败会回退；分数阈值需依据真实馆规校准。管理员可在知识库页面检查命中情况，读者只使用已发布资料。

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

图书借还只需 MySQL、API 和前端。启动 API 会创建缺失的 `books`、`book_copies` 和 `book_loans` 表，不修改已有同名表，也不删除原数据库。读者入口为“图书检索”和“我的借阅”，管理员入口为“书目与馆藏”和“借还审核”。操作步骤、接口、并发规则与隔离测试命令见 [实体图书业务使用与验收指南](docs/books-guide.md)。

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
node --experimental-vm-modules --test tests/*.test.mjs
npm run build

cd ..\backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/evaluate_rag.py
```

离线评估默认使用 30 条合成用例及假向量/假模型，输出命中、引用合法性、拒答与耗时指标，不调用云端，不代表真实检索质量。正式验收需人工建立真实文档评估集；`--live` 会真实调用服务并产生费用，参见指南。

本轮 RAG 增强已通过后端 246 项测试（含独立 MySQL 和真实 Chroma 测试）、前端 22 项测试与生产构建。四种文件已完成真实上传、索引、发布和入库核验；30 题三组检索对比、5 项真实问答/引用检查及浏览器验收通过。语料为 10 份合成文档，已在验收后停用；结果与局限见 RAG 指南，不能代表正式馆规上的准确率。

实体书阶段自动验证已通过：后端208项（包括5项独立 MySQL 并发验收、1项 MySQL 库存类型契约、2项真实本地 Chroma HTTP 测试及2项真实登录的 SQLite 完整借还流程）、前端19项测试与生产构建。MySQL 和 Chroma 测试需要显式开启；默认测试会跳过它们。复验命令与数据库隔离说明见 [图书指南](docs/books-guide.md#自动测试与复验)。另已通过本机浏览器点击完成借还流程及四个新页面的桌面/手机布局检查，记录见图书指南。这些结果仍不代表馆方现场验收或学校正式馆规的 RAG 验收已完成。

新数据库可以在 `backend` 目录运行 `scripts/seed.py` 创建管理员和图书馆演示空间。`scripts/convert_demo_labs.py` 只用于转换项目旧版官方演示数据，不会自动执行。
