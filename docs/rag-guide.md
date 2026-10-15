# 公开文档 RAG 使用与验收指南

第一版知识库用于公开馆规、预约说明等静态资料。默认 `RAG_ENABLED=false`，普通聊天继续调用 LangChain `ChatDeepSeek`。启用后，文档片段发送给配置的嵌入服务计算向量，检索到的片段发送给 DeepSeek 生成回答；上传前应确认资料可提供给这些服务。

## 结构与数据位置

```text
管理员上传 → 私有文件 → SQL持久任务 → 解析/切分 → BGE-M3 文档向量
                                            → Chroma HTTP → 管理员发布

知识模式提问 → 必要时改写追问 → BGE-M3 问题向量 → Chroma候选
             → SQL发布版本过滤 → DeepSeek带依据回答 → 引用校验 → 带登录凭证查看原文
```

| 组件 | 内容与默认位置 |
| --- | --- |
| MySQL | `knowledge_documents`、`knowledge_versions`、`knowledge_chunks`、`knowledge_jobs`，保存版本、正文、发布状态和持久任务 |
| 私有原文件 | `backend/data/knowledge/`，可用 `KNOWLEDGE_DIR` 调整；文件名由服务端生成 |
| 向量索引 | Chroma 独立 HTTP 服务，示例持久目录 `backend/data/chroma/` |
| 云端服务 | DeepSeek 生成；硅基流动 `BAAI/bge-m3` 生成 1024 维向量，分别配置密钥 |

知识原文件不存入公开 `/uploads`，也不通过静态服务器共享。登录用户只能通过来源接口查看当前有效发布版本的切片，停用或换版后旧来源可能返回不可用。备份时应一起备份 SQL、私有文件与 Chroma 数据；仅备份向量不能恢复正文与发布记录。

## 配置与启动

当前 `lab-agent-rag` 是完整项目的开发工作树，不是额外部署的前端服务。验证此分支时只启动这个目录中的一套 Vue 和 FastAPI；不要同时启动主目录的同端口进程。合入主项目后，统一从主目录启动。Chroma 和 worker 是额外后台组件。

首次在项目根目录打开 PowerShell：

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

手动编辑本地 `backend/.env`。数据库和 JWT 配置沿用 `.env.example`，RAG 相关配置如下；真实密钥不要复制进示例文件或聊天记录。

```dotenv
DEEPSEEK_API_KEY=填入本地真实密钥
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT_SECONDS=60
RAG_ENABLED=true
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=填入本地硅基流动密钥
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSIONS=1024
EMBEDDING_BATCH_SIZE=32
EMBEDDING_TIMEOUT_SECONDS=60
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8001
CHROMA_TIMEOUT_SECONDS=10
RAG_REQUEST_TIMEOUT_SECONDS=60
```

本方案使用硅基流动托管的 BGE-M3，无需本地 GPU。程序在 base URL 后添加 `/embeddings`；不要填写 `/chat/completions`。BGE-M3 使用固定 1024 维，配置也兼容单数 `EMBEDDING_DIMENSION`（两者只填一个）。批量 32 可根据服务限额调小。嵌入请求超时受知识问答总时间预算限制，60 秒不是额外叠加的等待时间。DeepSeek 与嵌入服务分别配置密钥。

保留百炼兼容方式：设置 `EMBEDDING_PROVIDER=dashscope`、`EMBEDDING_MODEL=text-embedding-v4`、`DASHSCOPE_API_KEY` 和与密钥地域匹配的 `DASHSCOPE_EMBEDDING_URL` 原生文本向量接口。不同 provider 的密钥不回退混用。

在四个终端分别启动以下进程。前三个终端的工作目录为 `backend`：

```powershell
# 终端1：Chroma，保留持久目录
.venv\Scripts\chroma.exe run --path .\data\chroma --host 127.0.0.1 --port 8001
```

```powershell
# 终端2：FastAPI，启动时创建缺失的知识库表
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# 终端3：持久索引与清理任务worker
.venv\Scripts\python.exe knowledge_worker.py
```

```powershell
# 终端4：项目根目录下的前端
cd vue-project
npm install
npm run dev
```

仅启动 API 不会自动处理索引任务。修改 `.env` 后重启 API 和 worker，让两者使用相同模型、地域、维度和私有目录。示例 Chroma 没有认证，仅监听本机；跨主机部署前需要单独设计网络访问控制和认证，不应把端口直接公开。

当前项目启动使用 `Base.metadata.create_all` 创建缺失表，不能迁移已经存在的同名旧表。更新已有部署时，应先备份并为字段变更执行受审查的数据库迁移；不要删除业务数据库来代替迁移。

## 管理员操作流程

1. 使用管理员账号打开“知识库管理”，上传馆方确认过的 TXT、Markdown、DOCX 或有文字层的 PDF，并填写准确标题。
2. 等待版本索引状态从排队转为处理中、就绪。失败时检查配置和服务，再对失败版本点击重试。索引就绪不会自动公开。
3. 检查资料版本和内容后发布。读者在 AI 助手选择知识库模式，问题才进入检索；普通聊天不会自动检索馆规。
4. 回答中的 `[1]` 等仅对应本轮来源。展开来源核对正文、页码或段落，不能只看模型回答。
5. 更新规则时上传新版本，待新索引就绪后发布；新版本失败不会替换旧的有效发布版本。
6. 停用后 SQL 立即阻止该文档参与检索，可再次发布就绪版本恢复。删除为不可逆管理操作，查询立即失效，向量与私有文件由 worker 后续清理。

支持格式的限制：TXT/MD 为 UTF-8；DOCX 保留段落及表格行列关系；PDF 按页提取文字。首期不支持旧版 `.doc`、含宏文档、加密文档或扫描件，不进行 OCR。默认单文件 10 MiB、解析文字 50 万字、PDF 200 页，DOCX 解压内容最多 20 MiB。超限或不可解析文件会返回中文错误。

同一文档重复上传相同内容和相同向量配置时复用已有版本，避免重复索引。不同文档条目视为独立资料，上传前请确认不是已有条目的重复副本。

更换 Embedding provider、模型、接口地址或维度时，指纹会选择新的独立 collection。旧向量不能混用：上传新版本并重新索引、发布；失败重试只能继续原向量空间，不承担模型迁移。当前没有双模型平滑切换，修改全局配置后旧空间资料不再参与新空间检索，应安排知识问答维护窗口完成重建和发布。

## 检索与能力边界

默认按 800 字切分、重叠 100 字；初始召回 8 条候选、最多使用 4 条，余弦距离阈值 0.6，上下文最多 6000 字符。检索仅采用 SQL 中已发布、当前有效版本且索引就绪、向量指纹匹配的切片；Chroma 元数据不是发布权限依据。模型返回前再次查询发布状态，降低生成期间停用造成的旧来源暴露。

追问改写仅用于向量检索，不能作为回答指令。文档与历史视为不可信资料；系统提示模型不得执行其中指令。缺少本轮引用或出现虚构数字引用时，后端保守返回依据不足。系统提示和引用检查不能证明事实准确或抵御所有提示注入，正式验收仍需真实模型和人工审阅。

| 响应 `retrieval_status` | 含义 |
| --- | --- |
| `not_requested` | 普通聊天；旧 API 响应保持原 `role/content` 结构 |
| `matched` | 找到当前有效证据并通过数字引用检查 |
| `no_match` | 没有达到要求的有效文档依据，明确拒绝编造 |
| `insufficient_evidence` | 检索后模型未形成带合法引用的回答，返回保守说明 |

向量接口、Chroma、生成服务错误和超时作为业务错误展示，不能伪装成没有资料。当前统一响应会在 HTTP 200 中携带非 200 的业务 `code`，调用方需同时检查业务码。

知识问答不能读取实时空闲、设施实时状态、个人预约，也不能替读者执行预约、审核或取消；这些能力需未来单独接入受控业务接口。本版不包含混合检索、重排模型、OCR、跨实例任务编排或实时工具。

## 可重复验证与评估

后端测试可以完全使用隔离 SQLite 和假服务；在未配置本地数据库的测试终端显式提供测试配置：

```powershell
cd backend
$env:DATABASE_URL='sqlite:///:memory:'
$env:JWT_SECRET_KEY='test-only-change-me'
$env:JWT_EXPIRE_HOURS='24'
$env:JWT_ALGORITHM='HS256'
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m pip check
```

前端在 `vue-project` 执行 `node --experimental-vm-modules --test tests/knowledge.test.mjs tests/chatConversation.test.mjs`，再执行 `npm run build`。默认离线评估可在 `backend` 单独运行，不需要云端 Key、MySQL 或已启动的 Chroma：

```powershell
.venv\Scripts\python.exe scripts/evaluate_rag.py
# 可选保存JSON报告（报告不含问题正文和密钥）
.venv\Scripts\python.exe scripts/evaluate_rag.py --output rag-evaluation-local.json
```

`tests/fixtures/rag_evaluation.json` 明确标记 `synthetic=true`，包含 30 条命中、无依据、停用、连续追问和不可信文档/引用异常用例。脚本将这些资料放入进程内 SQLite，注入确定性假向量、假检索和假模型；不上传资料，不调用任何云端服务。30/30 仅表示此组流程回归通过，不能换算成真实嵌入检索召回率、DeepSeek 事实准确率或提示注入防护通过率。

正式验收应由馆方依据真实、当前发布文档人工标注问题及对应文档 ID；覆盖中文同义问法、跨章节、追问、无答案、停用换版和恶意文档。建议先不少于 30 题，再根据失败样本迭代。质量阈值由馆方确认，当前 0.6 距离阈值尚需真实语料校准。

真实评估集格式示例（文档 ID 必须替换为当前实例的实际 ID）：

```json
{
  "name": "馆方人工标注验收集",
  "synthetic": false,
  "cases": [
    {
      "id": "manual-01",
      "question": "填写依据正式文档编写的问题",
      "category": "hit",
      "expected_status": "matched",
      "expected_document_ids": [12]
    },
    {
      "id": "manual-02",
      "question": "填写已确认文档没有依据的问题",
      "category": "no_match",
      "expected_status": "no_match",
      "expected_document_ids": []
    }
  ]
}
```

在正式资料已入库并发布、API/Chroma/worker 就绪后，由操作者手动运行：

```powershell
# 仅在本地终端设置已登录的用户JWT，不写入仓库
$env:RAG_EVAL_TOKEN='本地登录取得的JWT'
.venv\Scripts\python.exe scripts/evaluate_rag.py --live --dataset .\local-real-evaluation.json --api-base-url http://127.0.0.1:8000
```

`--live` 将真实调用 AI 接口并消耗嵌入服务及 DeepSeek 额度；默认合成集会被拒绝。脚本只发送问答请求，不上传或发布资料。报告指标包括：有目标文档用例的 hit@k/漏检数、返回数字引用合法率、应拒答用例的拒答率、状态准确率、错误数和端到端平均/P95 耗时。数字引用合法只检查当前返回来源编号，不能替代人工判断引用是否支持该结论。离线耗时也不能用于推断线上云端耗时。

## 常见问题

| 现象 | 检查项 |
| --- | --- |
| 普通聊天正常、知识模式提示未启用 | API 的 `RAG_ENABLED`、修改后是否重启 |
| 上传后一直排队 | worker 是否启动，API/worker 是否连接同一数据库与私有目录 |
| 向量服务未配置或不可用 | 所选 provider、对应 Key、接口地址、网络与额度 |
| 索引或检索服务错误 | Chroma 进程、端口、持久目录权限及超时 |
| 索引就绪但检索无依据 | 管理员是否已发布、是否停用、模型指纹是否匹配、真实阈值是否需要校准 |
| 新版本失败 | 旧发布版继续有效；修复问题后仅重试失败版本 |
| 老回答的来源打不开 | 文档已停用、删除或当前发布版本已替换 |
