# 公开文档 RAG 使用与验收指南

知识库用于管理员上传的公开馆规、预约说明等静态资料。默认 `RAG_ENABLED=false`，普通聊天继续调用 LangChain `ChatDeepSeek`。启用后，文档片段发送给配置的嵌入服务计算向量；开启重排时，候选片段还会发送给硅基流动重排服务，最终证据发送给 DeepSeek 生成回答。上传前应确认资料可提供给这些服务。读者无需上传文件。

## 结构与数据位置

```text
管理员上传 → 私有文件 → SQL持久任务 → 解析/切分 → BGE-M3 文档向量
                                            → Chroma HTTP → 管理员发布

知识模式提问 → 原问题 + 必要时改写追问 → SQL确定有效发布版本
             → BGE-M3 / Chroma语义召回 + 中文分词 / BM25关键词召回
             → RRF融合去重 → 可选BGE Reranker精排（失败回退）
             → 有界邻接片段 → SQL再次核验 → DeepSeek回答 → 引用校验 → 原文预览
```

| 组件 | 内容与默认位置 |
| --- | --- |
| MySQL | `knowledge_documents`、`knowledge_versions`、`knowledge_chunks`、`knowledge_jobs`，保存版本、正文、发布状态和持久任务 |
| 私有原文件 | `backend/data/knowledge/`，可用 `KNOWLEDGE_DIR` 调整；文件名由服务端生成 |
| 向量索引 | Chroma 独立 HTTP 服务，示例持久目录 `backend/data/chroma/` |
| 关键词索引 | API 进程内 jieba + BM25L 缓存，从 MySQL 当前发布正文重建，按向量指纹、有效版本和标题更新 |
| 云端服务 | DeepSeek 生成；硅基流动 `BAAI/bge-m3` 生成 1024 维向量，分别配置密钥 |

知识原文件不存入公开 `/uploads`，也不通过静态服务器共享。登录用户只能通过来源接口查看当前有效发布版本的切片，停用或换版后旧来源可能返回不可用。备份时应一起备份 SQL、私有文件与 Chroma 数据；仅备份向量不能恢复正文与发布记录。

## 配置与启动

RAG 已合入 `lab-agent`。前端、FastAPI、Chroma 和 worker 均从主项目目录启动；无需另一个 RAG 项目。Vue 的知识库管理和 AI 问答共用同一个 FastAPI。Chroma 和 worker 是后台组件，后续可用 Docker Compose 统一编排。

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
RAG_RETRIEVAL_MODE=hybrid
RAG_CANDIDATES=20
RAG_LEXICAL_CANDIDATES=20
RAG_FUSION_CANDIDATES=30
RAG_RRF_K=60
RAG_LEXICAL_MIN_COVERAGE=0.35
RAG_TOP_K=4
RAG_NEIGHBOR_CHUNKS=1
RERANK_ENABLED=false
RERANK_BASE_URL=https://api.siliconflow.cn/v1
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_API_KEY=仅在本地填写硅基流动密钥
RERANK_TIMEOUT_SECONDS=8
RERANK_MIN_SCORE=0
```

本方案使用硅基流动托管的 BGE-M3，无需本地 GPU。程序在 base URL 后添加 `/embeddings`；不要填写 `/chat/completions`。BGE-M3 使用固定 1024 维，配置也兼容单数 `EMBEDDING_DIMENSION`（两者只填一个）。批量 32 可根据服务限额调小。嵌入请求超时受知识问答总时间预算限制，60 秒不是额外叠加的等待时间。DeepSeek 与嵌入服务分别配置密钥。

配置项以 `backend/app/config.py` 的 `Settings` 为准。其他项目中的 `MODEL_API_KEY`、`MODEL_BASE_URL`、`MODEL_NAME` 应分别改为 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`；模型名须为对应服务实际支持的名称。未知的 `.env` 字段会触发 `extra_forbidden` 并阻止启动。当前代码不读取 `OCR_*`，仅填写 OCR 密钥不会启用扫描件识别。整理旧配置前，可将完整原文件备份至已被 Git 忽略的 `backend/data/local-config-backups/<时间>/.env`，再从运行配置移除未实现的字段；备份同样包含密钥，不应提交或分享。

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

首次启动时，先等待 API 输出 `Application startup complete`，再启动 worker。知识库表由 API 启动阶段创建，worker 提前启动可能因 `knowledge_jobs` 表尚不存在而退出；表创建完成后重启 worker 即可。

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

默认按 800 字切分、重叠 100 字。语义和关键词通道每个查询各取最多 20 条，RRF 融合后最多保留 30 条候选。追问同时检索原问题和改写问题，同一通道中重复命中不重复加权。中文分词保留 R-204、A4 等编号，BM25L 兼顾正文、标题和章节，并支持单篇小语料库。相同标题、章节和正文的候选去重；不同章节或标题的相同短句保留，避免混淆规则范围。

有效版本由 MySQL 决定，Chroma 查询先限定这些版本，再召回最近邻，避免草稿和旧版本挤占候选。关键词缓存也只包含有效版本。模型输入和返回前再次核验发布状态；向量元数据不能替代发布权限检查。

`RAG_RETRIEVAL_MODE=vector` 使用纯向量；`hybrid` 启用双路召回。未启用重排或重排失败时，按向量余弦距离不大于 `RAG_MAX_DISTANCE`（默认 0.6），或关键词覆盖率达到 `RAG_LEXICAL_MIN_COVERAGE`（默认 0.35）且存在有效词项匹配，筛选融合结果。RRF 和 BM25 分数不套用余弦距离阈值。

设置 `RERANK_ENABLED=true` 后，调用独立的 `BAAI/bge-reranker-v2-m3`，不改变 BGE-M3 向量或重建已有向量集合。`RERANK_API_KEY` 单独从本地读取；可以在本地填入同一硅基流动账号的有效 Key，代码不会隐式使用其他 provider 的密钥。一次请求有总时间预算，重排默认最多 8 秒并预留后续处理时间，不自动重试。超时、限流、缺少配置或异常响应时，返回经过基础筛选的 RRF 结果，并记录固定的降级日志；后台检索检查显示回退状态。

`RERANK_MIN_SCORE=0` 默认仅使用模型排序，不按尚未校准的绝对分数拒绝候选。真实联调曾发现正确证据分数为 0.073，以及跨章节问题的一条必要证据仅为 0.010；初设 0.15 会造成漏检。因此阈值应在正式语料及独立验证集上确定，不能当成答案正确概率。管理员可显式提高该阈值并比较漏检和误召回。无答案问题还需由生成环节根据证据拒答，并人工评估。

最终默认选取 4 条主证据，每条最多补充 1 个同版本相邻片段，上下文整体不超过 6000 字符。相邻片段保留独立的页码、章节和引用编号；设置 `RAG_NEIGHBOR_CHUNKS=0` 可关闭。关键词缓存适用于本项目的小中型馆规语料，首次查询或发布变更后会重建；大量语料时须测量构建耗时和内存，再选择专用全文检索服务。

追问改写仅用于向量检索，不能作为回答指令。文档与历史视为不可信资料；系统提示模型不得执行其中指令。缺少本轮引用或出现虚构数字引用时，后端保守返回依据不足。系统提示和引用检查不能证明事实准确或抵御所有提示注入，正式验收仍需真实模型和人工审阅。

| 响应 `retrieval_status` | 含义 |
| --- | --- |
| `not_requested` | 普通聊天；旧 API 响应保持原 `role/content` 结构 |
| `matched` | 找到当前有效证据并通过数字引用检查 |
| `no_match` | 没有达到要求的有效文档依据，明确拒绝编造 |
| `insufficient_evidence` | 检索后模型未形成带合法引用的回答，返回保守说明 |

向量接口、Chroma、生成服务错误和超时作为业务错误展示，不能伪装成没有资料。当前统一响应会在 HTTP 200 中携带非 200 的业务 `code`，调用方需同时检查业务码。

知识问答不能读取实时空闲、设施实时状态、个人预约，也不能替读者执行预约、审核或取消；这些能力需未来单独接入受控业务接口。本版包含混合检索和可选重排，仍不包含 OCR、跨实例任务编排或实时工具。

## 管理员检索检查与入库核验

“知识库管理”页面增加检索效果检查。输入问题，可以分别选择当前配置、语义检索、混合检索、混合检索加重排；仅影响本次检查，不修改读者问答配置。显示候选渠道、融合排名、最终入选排名、各自分数、阶段耗时和重排降级状态。展开命中行查看原文。此检查不调用生成模型，入选片段不意味着文档一定能回答问题。两种云端模型可能产生调用费用。

展开文档版本后，点击“核验入库”可查看 MySQL 正文数与 Chroma 向量数、缺失和多余记录数、集合名称和当前模型是否匹配。核验逐项比较切片 ID，不仅比较数量。新任务只有核验一致才会标记就绪；处理中核验仅代表当时状态，结束后应重新检查。核验最多读取 10 万条记录并受时间预算限制，超限明确报错。失败版本使用“重新处理”；旧空间或已就绪但损坏的版本通过上传新版本重建，不能仅凭修改状态恢复。

| 接口（均要求管理员） | 用途 |
| --- | --- |
| `POST /api/admin/knowledge/search` | `query` 为 1–1000 字；`strategy` 为 `current/vector/hybrid/hybrid_rerank`；`limit` 为 1–30，默认 4 |
| `GET /api/admin/knowledge/versions/{version_id}/index-status` | 核验指定未删除文档的版本，不修改数据 |

检索检查只返回当前发布、索引就绪、向量指纹匹配的正文；普通读者不能访问这两个接口。检查响应中的 `candidates` 是融合候选，`results` 是精排及筛选后的主证据，尚未扩展邻接片段。

## 三组真实检索对比

`scripts/evaluate_retrieval.py` 独立衡量候选召回与最终排序，不使用最终回答的引用代替召回结果。标注单位为文档；同一文档的重复切片只计一次。报告包含候选 Recall@20、最终 Recall@4、Hit@K、MRR@K、无答案误召回比例、平均/P95 耗时及重排成功/回退数。服务错误计入错误和漏检，不当成正确拒答。

先将资料上传、索引并发布，准备包含实际文档 ID 的本地数据集：

```json
{
  "synthetic": false,
  "cases": [
    {"id": "manual-01", "question": "本馆借阅上限与归还规则是什么？", "expected_document_ids": [12, 13]},
    {"id": "manual-02", "question": "资料中没有依据的问题", "expected_document_ids": []}
  ]
}
```

```powershell
# backend 目录；管理员 JWT 只放当前本地终端
$env:RAG_EVAL_TOKEN='本地管理员登录凭证'
.venv\Scripts\python.exe scripts/evaluate_retrieval.py --live --dataset .\data\real-retrieval.json --output .\data\retrieval-report.json
# 明确标记 synthetic=true 的合成数据需额外指定 --allow-synthetic
```

这个命令会顺序比较三种策略，真实调用嵌入和重排服务，不上传、发布或修改文档。默认使用本地 API；报告不包含问题正文、源文件或凭证。仓库中的 `tests/fixtures/retrieval_benchmark.json` 是 30 题合成素材，需要先上传并将 `expected_keys` 映射为当前实例的 `expected_document_ids`。正式验收必须另备馆方标注资料，并划分调参集与独立验证集。

## 可重复验证与评估

后端测试可以完全使用隔离 SQLite 和假服务；在未配置本地数据库的测试终端显式提供测试配置：

```powershell
cd backend
$env:DATABASE_URL='sqlite:///:memory:'
$env:JWT_SECRET_KEY='test-only-change-me'
$env:JWT_EXPIRE_HOURS='24'
$env:JWT_ALGORITHM='HS256'
$env:RAG_ENABLED='false'
$env:RERANK_ENABLED='false'
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m pip check
```

前端在 `vue-project` 执行 `node --experimental-vm-modules --test tests/*.test.mjs`，再执行 `npm run build`。默认离线评估可在 `backend` 单独运行，不需要云端 Key、MySQL 或已启动的 Chroma：

```powershell
.venv\Scripts\python.exe scripts/evaluate_rag.py
# 可选保存JSON报告（报告不含问题正文和密钥）
.venv\Scripts\python.exe scripts/evaluate_rag.py --output rag-evaluation-local.json
```

`tests/fixtures/rag_evaluation.json` 明确标记 `synthetic=true`，包含 30 条命中、无依据、停用、连续追问和不可信文档/引用异常用例。脚本将这些资料放入进程内 SQLite，注入确定性假向量、假检索和假模型；不上传资料，不调用任何云端服务。30/30 仅表示此组流程回归通过，不能换算成真实嵌入检索召回率、DeepSeek 事实准确率或提示注入防护通过率。

正式验收应由馆方依据真实、当前发布文档人工标注问题及对应文档 ID；覆盖中文同义问法、跨章节、追问、无答案、停用换版和恶意文档。建议先不少于 30 题，再根据失败样本迭代。质量阈值由馆方确认，当前 0.6 距离阈值尚需真实语料校准。

### 2026-10-16 本地真实服务联调记录

本次使用本机 MySQL、FastAPI、Vue、Chroma HTTP 和独立 worker，实际调用硅基流动 `BAAI/bge-m3`（1024 维）及本地所配的 DeepSeek `deepseek-v4-pro`。语料为明确标注的合成馆规，不能作为正式馆规验收结果。

- 上传 Markdown 后，worker 完成 6 个切片的真实嵌入与入库；未发布时查询返回 `no_match`。
- 发布后，开放时间、研讨室人数与时长、借阅数量与借期、取消与迟到、携带食品与饮水这 5 题均返回正确事实及合法数字引用；所有返回来源均通过原文预览接口逐一核对。
- 结合上一轮借阅回答追问续借次数和天数，正确返回一次、十五天及引用；7 次已发布状态下的问答（含无依据题、追问）耗时约 3.2–8.0 秒。
- 打印价格在资料中没有依据，返回 `insufficient_evidence`，未编造金额。停用合成文档后，原问题返回 `no_match`；合成文档最终保持停用。
- 额外探测 9 条有依据问题及 5 条无答案问题：最近切片的余弦距离分别为 0.202–0.446、0.468–0.608。阈值 0.6 会纳入其中 4 条无答案问题的候选，说明向量距离不能单独判断文档是否含有答案。该小样本不用于确定正式阈值，本地仍保留 0.6，后续用真实馆规和人工标注题校准。
- 后端 145 项测试全部通过（含 2 项实际 Chroma HTTP 测试）；前端 8 项测试与生产构建通过。前端构建仍有较大资源包提示。

本机详细问答、距离记录及服务日志保存在被 Git 忽略的 `backend/data/rag-local-acceptance/`，其中 `report.json` 不含密钥或登录凭证。此次只确认了真实服务链路和合成资料上的行为；正式文档质量、扫描件 OCR 及浏览器交互仍需分别验收。

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

### 2026-10-16 混合检索与重排联调记录

本轮使用真实 BGE-M3、硅基流动 `BAAI/bge-reranker-v2-m3`、DeepSeek、本机 MySQL 和 Chroma。10 份明确标注的合成文档覆盖 TXT、Markdown、DOCX、文字 PDF；PDF 使用英文文字层，问句为中文。所有文档经过上传、worker 索引、SQL/Chroma 实际 ID 核验和发布。

同一组 30 题（25 道有答案题，其中一道需要两份文档；5 道无答案题）的最终复测结果如下。重排采用默认 `RERANK_MIN_SCORE=0`，共 90 次检索请求，错误为 0，30 次重排全部成功、无回退。

| 策略 | 候选 Recall@20 | 最终 Recall@4 | MRR@4 | 无答案误召回 | 平均 / P95 耗时 |
| --- | --- | --- | --- | --- | --- |
| 纯向量 | 100% | 100% | 0.96 | 5/5 | 2.34 / 2.53 秒 |
| 向量 + BM25L + RRF | 100% | 100% | 0.92 | 5/5 | 1.99 / 2.57 秒 |
| 混合 + rerank | 100% | 100% | 1.00 | 5/5 | 2.83 / 3.19 秒 |

这些数字只描述此轮小样本。语料仅 10 份文档，小于候选窗口 20，因此候选召回 100% 不能证明大规模检索质量。此组混合融合的首位排序弱于纯向量，重排后有所改善；耗时受网络波动影响。无答案误召回表示检索仍返回候选，不代表生成模型一定编造答案，也不能据此宣称拒答能力完善。

初次尝试 `RERANK_MIN_SCORE=0.15` 时，最终 Recall@4 为 92%，无答案误召回为 1/5；其中正确的闭馆时间资料得分约 0.073，跨文档借还问题的两份正确资料约为 0.118 和 0.010，被统一阈值错误排除。因此默认先用重排排序，不把未校准的分数直接解释为答案置信度。调参使用过的题目不是独立验证集，正式门槛必须用另备真实资料验证，并同时观察漏检、误召回与最终回答。

- 5 项真实问答检查通过：研讨室位置人数、借期起算、静音区电话规则、读者证挂失均返回正确事实与引用；停车收费无依据时返回 `insufficient_evidence`。所有返回来源逐一打开并核对原文。
- 浏览器实测管理员三策略检查页面、实际入库核验、读者知识问答及原文预览；普通读者无法进入管理页。1440px 桌面与 390px 手机布局无页面横向溢出，无脚本或请求错误。
- 最终后端 246 项测试通过，包括隔离 MySQL 并发与真实 Chroma HTTP 持久化测试；前端 22 项测试、生产构建及 Python 依赖一致性检查通过。
- 合成文档验收后全部停用。本地配置和不含凭证的验收报告位于 Git 忽略范围；密钥未提交，未执行推送。

本机详细结果保存在 `backend/data/rag-hybrid-acceptance/` 下的 `comparison.json`、`comparison-initial-threshold.json`、`qa.json` 与浏览器报告/截图。当前完成的是功能开发和合成语料真实服务联调；正式馆规评估、规模压测和 OCR 不在本次完成范围。

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
