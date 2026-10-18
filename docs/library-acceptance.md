# 华科官方资料与效果验收

本阶段为阅见简历项目接入华中科技大学图书馆官方公开文字资料，建立可复现的导入、知识问答与统一聊天验收流程。原馆资料属于 `external_reference`，不代表学校授权、系统接入了原馆业务，或阅见采用了原馆政策。

阅见当前业务仍为每人同时借阅最多 5 册、借期 30 天；华科本科生的 20 册、4 周是另一机构的公开参考规则。实时库存、借还与空间预约由本项目数据库校验。

## 资料范围与追溯

固定资料见 [来源清单](../evals/hust-library/sources.json) 与 [语料说明](../evals/hust-library/README.md)。2026-10-18 17:36:23（北京时间）采集了 8 篇官方公开文章：规章制度、校园卡管理、各类读者借书权限、图书外借、图书预约、图书续借、座位网络预约规则和座位预约管理办法。

- 每篇保存官方链接、适用机构、采集时间、规范化文字快照与 SHA256，严格校验 `lib.hust.edu.cn` 来源。
- 表格保留行列关系，快照固定 UTF-8/LF，避免 Windows 换行转换改变哈希。
- 官方接口本次没有明确发布日期；`published_at`、`effective_at` 为空。创建、更新与采集时间不作为生效日期。
- 4 张图片没有做 OCR；纯图片办事流程没有纳入文字证据。座位管理中的试运行描述不作为今天的开放安排或容量。
- 本地原始 JSON、响应哈希和图片遗漏记录保存在 `backend/data/hust-library-acceptance/capture-report.json`，不将运行数据或凭证提交 Git。

`library_corpus_sources` 是新增登记表，将 `(corpus_key, source_key)` 固定映射到知识文档。导入仍复用现有上传、worker 索引、版本发布与停用流程：同内容重跑不增加版本，内容变化建立新版本；新版本就绪并显式发布前，旧发布版本继续服务。登记表保存最近一次快照元数据，每个版本的私有 Markdown 另存当时的来源与哈希，便于历史追溯。

导入会先检查全部文件、哈希和来源冲突；不允许来源键重新绑定到另一 URL。默认仅预览，`--apply` 才写入，`--publish` 只发布已就绪版本。登记锚点先持久化，上传中断后可复用，避免产生重复文档。失败索引需明确 `--retry-failed`，不会无限重试。

## 导入与更新

准备 MySQL、API、Chroma 和 worker，配置方法见 [RAG 指南](rag-guide.md)。下列命令均在 `backend` 执行，不引入新依赖：

```powershell
# 预览增量表和导入；已有登记表时 SQL 列表为空
.venv\Scripts\python.exe scripts/upgrade_library_corpus.py
.venv\Scripts\python.exe scripts/import_library_corpus.py ../evals/hust-library/sources.json --snapshot-root ../evals/hust-library/snapshots

# 确认本地开发实例后写入；已有表时升级不会重复建表
.venv\Scripts\python.exe scripts/upgrade_library_corpus.py --apply
.venv\Scripts\python.exe scripts/import_library_corpus.py ../evals/hust-library/sources.json --snapshot-root ../evals/hust-library/snapshots --apply --output data/hust-library-acceptance/import-queued.json

# worker 独立终端：等待 8 份资料索引状态全部 ready
.venv\Scripts\python.exe knowledge_worker.py

# 另一个终端：发布并保存真实文档/版本绑定
.venv\Scripts\python.exe scripts/import_library_corpus.py ../evals/hust-library/sources.json --snapshot-root ../evals/hust-library/snapshots --apply --publish --output data/hust-library-acceptance/bindings.json
```

默认导入管理员账号为 `admin`；其他有效管理员可传 `--admin 用户名`。保留 `bindings.json`，后续评测校验其快照哈希、文档 ID、版本 ID 和实际发布状态，不使用其他实例的数字 ID。

需更新官网资料时，先采集到新目录并人工比较，避免覆盖已验收的快照：

```powershell
.venv\Scripts\python.exe scripts/capture_library_corpus.py --output-dir data/hust-library-refresh --manifest data/hust-library-refresh/sources.json
```

采集器只请求明确列出的 8 篇公开文章，不登录、不扩展爬取、不识别图片。审核变化后再建立新语料/题目版本并导入。

## 50 题与验收标准

题目固定为 20 道调参题和 30 道验证题，共 42 道有依据题、8 道应拒答题。覆盖直接问题、同义表达、多轮追问、跨章节、无答案、机构范围冲突与要求编造引用的指令。编号、标准化问题和主要事实组不跨组重复；全部证据摘录必须能在固定哈希快照中逐字核对。

这是一份开发代理依据真实原文辅助编写的项目自建题集，标记为 `agent_assisted/pending_human`；不是收集的真实读者问题，也未完成独立人工审核。验证题在真实模型运行前冻结；同一作者参与两组编写，不宣称为独立馆方基准。若查看验证失败后修改系统，后续同集运行须标为回归，不能宣称全新独立验证。

评测同时检查：

1. 管理员真实检索 API 上纯向量、混合、混合加重排三种策略的文档 Recall@4、MRR、无答案候选误召回及耗时。
2. 知识 API 实际回答的状态、合法引用、**实际引用**的预期来源覆盖、引用切片中的原文摘录覆盖、原文预览及发布版本一致性。
3. `/api/conversations`、`hint=auto` 的自动路由和真实前序消息，读取本轮任务中的 RAG 答案，避免把协调器处理提示当作回答。
4. 人工审核后的答案正确性与引用是否支持结论。未审核时这两项为 `null`，不会用模型判断或契约通过率冒充人工正确率。

检索标注按文档计算，回答证据可用 `expected_source_groups` 表示等价资料；每组引用到一份即可。返回但没有引用的候选不计入证据覆盖。按摘录检查是自动代理指标，不足以证明答案里的每项事实都正确。

自动门槛为：完整执行、服务错误 0、发布状态前后一致、契约通过率至少 90%、数字引用合法率 100%、应拒答成功率至少 90%；启用检索对比时还要求混合加重排的文档 Recall@4 至少 90%。这些是项目开发门槛，未经馆方确认。任一不满足，报告保留失败结论。

显式涉及“本系统/阅见”的知识问题在检索前过滤已登记外部馆规；协调器委派知识步骤时同时保留本轮用户原文，防止改写丢失机构或否定限定。回答外部馆规会带服务端适用范围说明。知识回答没有本系统规则依据时应拒答，不会自动改业务参数。

## 运行评测

```powershell
.venv\Scripts\python.exe scripts/evaluate_library.py check --manifest ../evals/hust-library/sources.json --dataset ../evals/hust-library/validation.json --other-split ../evals/hust-library/calibration.json --snapshot-root ../evals/hust-library/snapshots

# 仅在本地终端设置有效管理员登录令牌；不要写入文件或 Git
$env:RAG_EVAL_TOKEN='本地管理员登录取得的JWT'

.venv\Scripts\python.exe scripts/evaluate_library.py run --live --manifest ../evals/hust-library/sources.json --dataset ../evals/hust-library/calibration.json --other-split ../evals/hust-library/validation.json --snapshot-root ../evals/hust-library/snapshots --bindings data/hust-library-acceptance/bindings.json --entrypoint both --retrieval --output data/hust-library-acceptance/calibration-report.json

# 调参完成并固定代码/配置后，再运行验证集；保留首次报告
.venv\Scripts\python.exe scripts/evaluate_library.py run --live --manifest ../evals/hust-library/sources.json --dataset ../evals/hust-library/validation.json --other-split ../evals/hust-library/calibration.json --snapshot-root ../evals/hust-library/snapshots --bindings data/hust-library-acceptance/bindings.json --entrypoint both --retrieval --output data/hust-library-acceptance/validation-report.json

Remove-Item Env:RAG_EVAL_TOKEN
```

`both` 表示每题各运行知识 API 与统一聊天入口，因此 30 道验证题产生 60 次计分回答；前序追问额外发起真实消息，包含在该题耗时中。检索对比每题还有三次真实检索。调用会使用当前模型服务额度。评测仅自动推进当前任务的只读回答，不代替选择、确认或业务提交；连续 3 次服务异常会提前停止，不能给出通过结论。

每次输出 JSON、逐题 Markdown 和空白 `*.reviews-template.json`，审核表以报告哈希绑定本次实际回答。复制模板后，由人工逐项检查题目标注、答案、引用切片、适用机构和时间条件，填写实名或可追溯的审核标识、`answer_correct`、`citations_support` 与备注。

```powershell
.venv\Scripts\python.exe scripts/evaluate_library.py review --report data/hust-library-acceptance/validation-report.json --reviews data/hust-library-acceptance/validation-reviews.json --output data/hust-library-acceptance/validation-reviewed.json
```

`review` 不重新调用模型；审核表缺项时保持待审核，报告不匹配或非布尔判断会拒绝。人工修改题目标签后，应生成新数据版本、重新评测，不能篡改旧报告。

审核时以报告固定的快照和发布版本为准，逐项核对数字、读者类型、例外条件和适用时间，不能只看有没有 `[1]`。应拒答题若正确说明依据不足且未引用无关资料，可将两项判断均填为 `true`；服务错误不能判为正确答案。缺少外部政策依据也不表示系统具有该业务能力，例如参考资料提到续借，并不表示阅见已经实现续借。

## 本次执行记录

本地实际使用 MySQL、Chroma HTTP、BGE-M3（1024 维）、BGE reranker v2 m3 和 DeepSeek `deepseek-v4-pro`。8 份资料均为发布 v1，46 个切片逐一通过 SQL/Chroma 审计，无缺失、无多余向量。评测结束后重复导入，8 个文档、8 个版本及全部绑定保持一致，没有新增版本。真实报告、运行版本、逐题回答、空白审核模板及浏览器截图保存在 Git 忽略的 `backend/data/hust-library-acceptance/`。

本轮修复了统一聊天原文弹窗字段不匹配、评测器误读协调器提示、知识步骤改写丢失“本系统”限定，以及明确拒答仍附无关引用导致状态误判四项问题。拒答处理支持模型明确的 `NO_EVIDENCE` 信号及“资料/证据/依据不足”开头的保守识别，不是任意文本的事实正确性判定器。首次调参报告和诊断记录保留，不将工具错误覆盖成一次通过。

最终真实验收固定代码为 `25701f1347c22f36ad3e3b0d161a595235fc2fd1`；配置为 hybrid、重排启用、`RAG_MAX_DISTANCE=0.6`、候选 20、Top K 4、相邻切片 1、`RERANK_MIN_SCORE=0`。阈值没有按验证题调整。最终调参复测与首轮验证在同一代码冻结后并行运行，期间没有改运行代码、配置或发布版本；本地耗时包含开发机并发与云端波动，不作为压力测试结论。

最终后端全量 **446 项**通过，无跳过，包含隔离 MySQL 临时库的并发测试和实际 Chroma HTTP；离线 Agent Harness **112 项**、前端 **51 项**、变更文件的 Prettier 检查及生产构建通过。生产构建仍有既有的大资源包提示。

Edge 真实浏览器在 1440×1000 桌面与 390×844 手机视口验证了一个输入框中的 4 轮对话：本科生借阅权限、研究生短追问、打印价格无依据、原馆规则与本系统范围冲突；官方原文弹窗正常显示，刷新保留四轮，7 张截图无页面横向溢出，脚本异常为 0。前期浏览器脚本的消息等待与弹窗遮罩动画问题单独留有报告，最终运行通过；它们不计为模型正确率样本。

最终调参 **39/40（97.5%）**、首次验证 **59/60（98.33%）**满足项目自动门槛，服务错误为 0、发布版本前后一致。分入口结果如下；同一题运行两次不代表两份独立问题样本。

| 分组 / 入口 | 自动契约通过 | 命中回答引用格式合法率 | 应拒答成功 | 平均 / P95 耗时 |
| --- | --- | --- | --- | --- |
| 调参 / 知识 API | 20/20 | 100% | 3/3 | 7.13 / 9.66 秒 |
| 调参 / 统一聊天自动识别 | 19/20 | 100% | 3/3 | 10.26 / 12.09 秒 |
| 验证 / 知识 API | 30/30 | 100% | 5/5 | 7.63 / 19.98 秒 |
| 验证 / 统一聊天自动识别 | 29/30 | 100% | 5/5 | 11.29 / 28.68 秒 |

验证集 30 题的真实检索对比如下。90 次检索错误为 0；混合加重排 30 次均应用成功，无回退。

| 策略 | 候选 Recall@20 | 最终 Recall@4 | MRR@4 | 无答案候选误召回 | 平均 / P95 耗时 |
| --- | --- | --- | --- | --- | --- |
| 纯向量 | 100% | 96% | 0.8667 | 5/5 | 2.88 / 3.10 秒 |
| 混合 | 100% | 96% | 0.9000 | 5/5 | 2.86 / 3.05 秒 |
| 混合加重排 | 100% | 100% | 0.9800 | 5/5 | 3.51 / 3.93 秒 |

三种检索策略都会为无答案问题返回候选，不能把召回或重排分数直接解释为答案可靠性。最终问答层在两入口各 5 道无答案验证题上通过拒答检查。**答案事实正确率、引用对结论的语义支持率依然为空，人工复核覆盖率为 0。**

保留的失败项：

- 调参 `c10:conversation`：“华科图书预约支持预约哪些状态或馆区的书？”统一入口返回依据不足，未覆盖《图书预约》中的已借出及其他馆区在架可外借图书。
- 验证 `v20:conversation`：“华科图书还没过期，但被另一位读者预约了，我还能续借吗？”统一入口返回依据不足，未覆盖《图书续借》的不能续借规则。对应知识 API 通过自动检查。

这两项属于有答案问题的证据获取/回答失败，不能算正确拒答。验证失败没有被用于修改代码或标签；未来针对它改进后，同一验证集只作为回归，并应另备新验证题。

可随 Git 分享的聚合证据见 [acceptance-summary.json](../evals/hust-library/acceptance-summary.json)，包含运行版本、题集与报告哈希、分入口指标和失败题号，不包含登录凭证或验收账号身份。完整本地材料如下；重跑时改用新输出文件名，避免覆盖首轮记录。

| 材料 | 本地路径（相对项目根目录） |
| --- | --- |
| 最终调参 JSON / Markdown / 空白审核表 | `backend/data/hust-library-acceptance/calibration-release-report.*` |
| 首次验证 JSON / Markdown / 空白审核表 | `backend/data/hust-library-acceptance/validation-report.*` |
| 初轮及中间调参报告 | `backend/data/hust-library-acceptance/calibration-report.*`、`calibration-final-report.*` |
| 固定运行版本与非敏感配置 | `backend/data/hust-library-acceptance/*-runtime.json` |
| 入库审计与重复导入 | `backend/data/hust-library-acceptance/index-audit.json`、`idempotence-report.json` |
| 最终浏览器与清理记录 | `backend/data/hust-library-acceptance/browser-report.json`、`cleanup-report.json` |

本阶段两个合成验收账号已禁用，94 个验收会话的历史保留；没有提交借阅或空间预约。官方资料保持发布，已有用户、书目和空间未用于提交验收业务。

## 仍需完成的工作

- 由人工审核题目和真实答案，填写本次报告对应的审核表；目前没有馆方现场验收或人类语义正确率结论。
- 改善上述两道题在统一委派后的证据检索表现，并用新的独立验证题复验。
- 按真实读者问法扩大独立标注集和语料规模，再确定阈值、性能与持续回归门槛。8 份资料的小样本不能代表大规模知识库效果。
- 图片/OCR、官网变化定期同步、实时原馆业务、管理员审批 Agent、多实例部署及跨设备会话历史仍在后续范围。

简历可描述“接入华科官方公开资料，构建版本可追溯 RAG 语料与 50 题分组评测，验证统一聊天路由、引用证据和拒答行为”；没有人工审核前，不写“馆方验收通过”或“答案准确率达到某值”。
