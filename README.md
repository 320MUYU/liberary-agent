# 阅见 · 图书借阅与学习空间预约系统

阅见是一套面向高校图书馆的实体图书借还与学习空间预约系统。读者可以检索图书、申请借阅和归还，也可以查询研讨室、自习室和多媒体空间并提交分时预约；管理员维护书目、馆藏副本、空间、设施和账号，确认实体书借出与归还并审核预约。第一版借期为30天，每人最多同时借阅5册，不含续借和罚款。

## 技术栈

- 前端：Vue 3、Vite、Vue Router、Element Plus、Axios
- 后端：FastAPI、SQLAlchemy、MySQL、JWT、bcrypt
- AI 对话：LangChain、DeepSeek；可选 RAG 使用 `BAAI/bge-m3`、Chroma、中文 BM25L 与 RRF 融合，可开关硅基流动 `BAAI/bge-reranker-v2-m3` 重排
- 多智能体：LangGraph 协调器、独立图书/空间子任务、SQLite 检查点、MCP、逐项确认与幂等回执

项目为了兼容既有数据库，后端内部继续使用 `Lab`、`Equipment`、`lab_id` 与 `/api/lab` 等名称；产品界面统一使用“学习空间”和“设施”。

## 已实现功能

- 注册、登录、JWT 鉴权和读者资料维护
- 图书检索、详情与实际馆藏库存展示
- 公开书目按具体版次导入、来源追溯及知识库同步，不自动创建馆藏副本
- 读者申请借阅、取消待确认借出申请、申请归还和查看借阅历史
- 管理员维护书目及副本、上下架、拒绝申请、确认借出和确认归还
- 学习空间查询、筛选、封面和设施展示
- 空间预约、容量校验、时段冲突检查和取消规则
- 管理员维护读者、空间、设施并审核预约
- 读者站内铃铛、分页通知、已读状态和业务详情跳转；预约审核、借还结果及到期/逾期提醒，见 [读者通知指南](docs/reader-notifications-guide.md)（代码已完成，本机 Docker 更新待环境恢复）
- DeepSeek 多轮对话、公开文档知识问答与来源引用
- 管理员知识文档上传、索引任务、版本发布、停用与失败重试
- 管理员对比向量、混合及重排检索，查看召回原文与实际 Chroma 入库记录
- 管理员逐题审核 AI 回答与引用证据，保存草稿、提交人工判断、查看指标并导出报告
- 阅见 AI 统一聊天：自动选择普通回答、知识、图书与空间能力，支持本轮能力偏好、连续追问、多个任务和最近对话恢复
- 多 Agent 协作：知识、图书与空间顺序处理组合需求；自然语言补充预约草稿、逐项选择与确认、来源预览、累计预算及部分成功恢复
- 华科图书馆公开参考资料：来源/快照哈希/版本追溯、幂等导入、机构范围隔离与 50 题分组评测
- 桌面端、平板和移动端响应式界面

## AI 能力边界

读者统一从“阅见 AI”聊天窗口使用普通回答、知识问答、图书借还与空间预约，直接输入需求或点击本轮能力偏好即可，聊天记录保持连续。RAG 配置默认关闭；启用后，管理员已发布文档可用于有来源的知识问答，资料不足时明确说明。知识文档放在私有目录，不通过公开 `/uploads` 提供。

协调器结合服务端近期会话和任务结果，直接回答或规划至多三个知识、图书、空间步骤；各专家沿用既有工具权限与独立业务任务。找书后选择并确认才提交借阅申请，归还仍需管理员确认实体书；预约条件可在聊天中补充为草稿，用户核对、选择空间并再次确认才提交。待审核预约不锁定时段。消息文字不能代替业务确认，只查询的步骤不能提交申请。管理员审批 Agent、多实例部署和跨设备历史列表仍待开发。数字引用有效不等于事实正确，正式馆规仍需人工验收；仓库的合成测试资料不是学校馆规。

统一聊天的整体架构、执行流程、开发流程图、API、升级与验收说明见 [统一会话与多 Agent](docs/unified-conversation.md)。旧助手 API 保留兼容。

新增服务的启动方式、确认流程及恢复说明见 [Agent 使用与验收指南](docs/agent-guide.md)。MCP 模式下，借阅助手需要 Vue、FastAPI、MCP 三个进程；完整 RAG 再加 Chroma 和索引 worker。LangGraph 随 API 运行，Harness 按需测试，无须另起常驻进程。

配置、启动顺序、文档发布和评估见 [RAG 使用与验收指南](docs/rag-guide.md)。

华中科技大学图书馆的 8 篇官方公开文字资料作为外部参考入库，共 46 个切片；本系统业务仍为 5 册/30 天，不直接套用原馆政策。固定快照、20 道调参题/30 道验证题、真实模型结果与人工审核流程见 [官方资料与效果验收](docs/library-acceptance.md)。题目由开发代理辅助编写，答案正确性仍待人工审核，不代表馆方授权或现场验收。

公开书目导入、重复检查和知识库同步见 [公开书目使用与验收指南](docs/catalogue-guide.md)。本地已导入 AI / Agent、儿童与历史各 10 本真实书目，30 份元数据文档已发布，共 59 个切片；不含书籍正文。公开目录中的书目不代表本馆已有实体副本，实际库存由管理员登记。

检索支持保留原问题与追问改写、中文关键词和向量双路召回、RRF 融合、去重、可选模型重排与相邻切片补全。重排失败会回退；分数阈值需依据真实馆规校准。管理员可在知识库页面检查命中情况，读者只使用已发布资料。

## 本地运行

### Docker 本机部署

完整 Docker 服务组合及现有数据迁移已提供，浏览器入口为 **http://localhost:18081**。使用原有账号和密码登录；MySQL、知识文档、Chroma 与 Agent 检查点保存到独立数据卷，原本机数据保留。

首次准备、迁移、启动、停止和恢复说明见 [Docker 本机部署](docs/docker-guide.md)。本机完成迁移后，日常启动只需在仓库根目录执行：

```powershell
./infra/docker/compose.ps1 up -d --wait --wait-timeout 180
```

以下为原开发环境的运行与验收记录。

2026-10-18 新增 [AI 效果审核管理页面](docs/evaluation-review-guide.md)：支持导入报告、草稿与提交、并发冲突检测、人工统计和 CLI 兼容导出。聊天与审核页统一支持 Markdown 排版，审核可切换原始文本；管理员菜单显示预约、借还和 AI 审核待办数量，铃铛提供分类入口，处理成功后刷新数量。后端471项（含独立 MySQL、Chroma，无跳过）、前端78项、离线 Harness 112项、Prettier与生产构建通过。桌面和手机浏览器14项检查通过。本地116条真实回答已导入，本轮验收时2条已人工提交、114条待审核；测试只修改独立临时库中的合成记录。旧库可执行 `backend/scripts/upgrade_evaluation_reviews.py --apply` 增量建表，更新前端依赖后重启后端。

2026-10-18 官方资料阶段：后端 446 项（含独立 MySQL、Chroma，无跳过）、离线 Agent Harness 112 项、前端 51 项及生产构建通过。真实模型验证的自动契约检查为知识入口 30/30、统一聊天入口 29/30，语义正确性待人工审核；未通过项和复现方法见 [验收记录](docs/library-acceptance.md#本次执行记录)。

2026-10-18 统一会话已完成：后端 404 项（含独立 MySQL、Chroma，无跳过）、离线 Agent Harness 111 项、前端 50 项、Prettier 与生产构建通过。真实模型/MCP、桌面和手机验证了单一聊天窗口内的多能力组合、条件补充、逐项确认、重复确认与刷新恢复。已有数据库可预览并执行 `backend/scripts/upgrade_agent_conversations.py --apply`；本机已创建两张会话表。详见 [统一会话与多 Agent](docs/unified-conversation.md)。

2026-10-17 组合任务阶段验证：后端364项（含独立 MySQL 和 Chroma）、离线 Agent Harness 94项、前端45项、Prettier检查及生产构建通过。真实模型/MCP 已完成图书与空间两个专家的逐项确认、刷新恢复和重复提交验收；桌面与手机布局通过。旧库先预览并执行 `backend/scripts/upgrade_agent_workflows.py --apply` 创建两个新表，本机已完成。操作、API、预算和验收局限见 [组合任务与多智能体指南](docs/agent-guide.md#组合任务与多智能体2026-10-17)。

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

公开书目阶段已通过后端 279 项测试（含 MySQL 和 Chroma）、前端 26 项测试及生产构建；30 份文档的真实 Chroma 入库审计、三类真实问答与引用原文预览均通过。记录见公开书目指南；本轮问答检查不代表已完成大规模召回率评估。

实体书阶段自动验证已通过：后端208项（包括5项独立 MySQL 并发验收、1项 MySQL 库存类型契约、2项真实本地 Chroma HTTP 测试及2项真实登录的 SQLite 完整借还流程）、前端19项测试与生产构建。MySQL 和 Chroma 测试需要显式开启；默认测试会跳过它们。复验命令与数据库隔离说明见 [图书指南](docs/books-guide.md#自动测试与复验)。另已通过本机浏览器点击完成借还流程及四个新页面的桌面/手机布局检查，记录见图书指南。这些结果仍不代表馆方现场验收或学校正式馆规的 RAG 验收已完成。

新数据库可以在 `backend` 目录运行 `scripts/seed.py` 创建管理员和图书馆演示空间。`scripts/convert_demo_labs.py` 只用于转换项目旧版官方演示数据，不会自动执行。


主题找书阶段已通过后端290项（含 MySQL 与 Chroma）、前端28项、生产构建和30项离线 Agent Harness。三类真实主题检索均命中，25条来源归属校验通过，未发生借阅写入；桌面与手机浏览器恢复及预览通过。详情见 [Agent 指南](docs/agent-guide.md#主题找书与知识库联动2026-10-16)。主题推荐仅依据元数据，不推断适读年龄或正文内容；无馆藏仍可查看，不能提交借阅。

个人借阅查询与申请归还阶段已通过后端310项（含 MySQL、Chroma，无跳过）、前端31项、生产构建和47项离线 Agent Harness。真实模型经 MCP 完成个人查询、取消、确认归还和管理员确认后的状态刷新；桌面与手机恢复验收通过。已有 Agent 数据库需先执行 `scripts/upgrade_agent_returns.py` 预览，再以 `--apply` 添加两个类型字段，旧任务默认 `borrow`；本机已升级。操作和验收记录见 [Agent 指南](docs/agent-guide.md#我的借阅与申请归还2026-10-16)。

空间预约阶段已通过后端339项（含 MySQL、Chroma，无跳过）、前端39项、生产构建和70项离线 Agent Harness。真实 DeepSeek/MCP、桌面与手机确认及刷新恢复、维护/容量/冲突、取消、通过和驳回验收均通过。已有数据库需停 API/MCP，预览并执行 `scripts/upgrade_agent_reservations.py --apply` 创建独立操作表，再预览并执行 `scripts/upgrade_space_reservation_schema.py --apply` 兼容旧表备注；保留全部记录，本机已完成。原 MySQL `TIME` 列保留，代码兼容其返回类型。详细步骤、限制和验收记录见 [Agent 指南](docs/agent-guide.md#空间预约2026-10-16)。
