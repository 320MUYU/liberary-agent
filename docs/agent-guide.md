# 图书借阅 Agent：启动、操作与验收

第一条链路已实现：找书 → 用户选择具体书目 → 用户确认申请 → 待管理员确认。入口是 `/assistant` 页面右上角的“图书借阅助手”。模型使用现有本地 DeepSeek 配置，LangGraph 随 FastAPI 运行，不需要单独启动。

本阶段只提供查书和申请借阅；申请归还、空间预约、管理员确认借出、组合任务规划及多 Agent 尚未接入。原有业务页面继续可用。

## 怎么启动

先确保 MySQL 服务运行，并在 `backend` 安装更新后的依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

数据库与 DeepSeek 配置仍只保存在本地 `backend/.env`。新增配置均有默认值：

```dotenv
# local：进程内调用同一业务工具；mcp：经本地 MCP 服务调用
AGENT_TOOL_TRANSPORT=mcp
AGENT_MCP_URL=http://127.0.0.1:8002/mcp
# 可选；默认 backend/data/agent/checkpoints.sqlite
# AGENT_CHECKPOINT_PATH=D:/Ai-Learning/Project/lab-agent/backend/data/agent/checkpoints.sqlite
```

仓库默认 transport 为 `local`，本次本地验收已设置为 `mcp`。修改配置后重启 FastAPI；改了 MCP 使用的数据库/JWT 配置时也重启 MCP。无需新增模型密钥。

完整系统共五个终端；仅使用借阅助手时启动前三项即可。每项在各自终端保持运行，建议后台工具服务先于 API 和前端启动。

| 服务 | 终端工作目录 | PowerShell 命令 |
| --- | --- | --- |
| Vue | `lab-agent/vue-project` | `npm run dev` |
| FastAPI | `lab-agent/backend` | `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` |
| MCP | `lab-agent/backend` | `.\.venv\Scripts\python.exe -m uvicorn app.mcp.library:app --host 127.0.0.1 --port 8002` |
| Chroma（RAG 使用） | `lab-agent/backend` | `.\.venv\Scripts\chroma.exe run --path .\data\chroma --host 127.0.0.1 --port 8001` |
| 索引 worker（文档入库使用） | `lab-agent/backend` | `.\.venv\Scripts\python.exe knowledge_worker.py` |

打开 `http://localhost:5173`。使用 `local` transport 时无需 MCP 终端，借阅助手仍复用相同业务契约。Harness 是按需运行的测试程序，不是常驻服务。开发终端可用 Ctrl+C 停止对应服务；若端口已占用，先确认是否已有该项目服务运行，避免重复启动。

首次启动 API 会创建缺失的 `agent_runs`、`agent_actions` 表，不清空现有业务数据。检查点文件只保存图执行状态；MySQL 中的操作记录和借阅记录才是写入回执的依据。检查点和本地验收数据位于 Git 忽略的 `backend/data/`，其中包含用户查询和书目信息，应按应用私有数据保管。

## 用户操作

1. 登录，进入“AI 空间助手”，切换到“图书借阅助手”。
2. 输入书名、作者、ISBN 或简短需求，例如“找 Python 入门书”。模型最多调用四轮、执行八次只读工具；根据查询结果给出书目卡片。
3. 核对作者、出版社和 ISBN，点击“选择这本书”。此时只生成确认预览，不创建借阅。
4. 点击“确认提交申请”或“取消本次申请”。确认有效期10分钟；提交时重新检查书目信息、账号状态、实际库存和重复申请。
5. 成功后显示申请编号与“待管理员确认”，通过“我的借阅”查看最新业务状态。申请不占库存，不保证最终借出。

刷新页面后重新选择借阅助手，会从当前浏览器会话保存的任务编号恢复。任务有效期24小时。浏览器只保存任务编号，不保存 MCP 凭证。页面显示的是本次申请回执；之后管理员可能已处理申请，当前状态以“我的借阅”为准。

网络中断时先点“刷新任务状态”。如果执行未结束，可点“继续未完成任务”；即使借阅已提交而响应丢失，恢复后也会读取原回执，不再次创建。取消已提交的申请应去“我的借阅”；确认卡片的取消仅用于尚未提交的操作。

## 执行结构

```mermaid
flowchart LR
    Q[找书需求] --> R[有界 ReAct 查询]
    R --> S[持久化暂停：选择书目]
    S --> P[生成确认记录]
    P --> C[持久化暂停：确认或取消]
    C --> A[重新校验并幂等执行业务]
    A --> E[返回待管理员确认回执]
```

- `app/agent/tools.py` 定义严格参数、只读工具白名单和安全错误。模型不能传入用户身份，也没有写工具。
- `app/agent/graph.py` 控制查询循环与两个暂停节点，保存工具决策，不保存模型内部推理或云端响应元数据。工具故障与无匹配书目区分显示。
- `app/agent/runtime.py` 验证任务归属，通过数据库租约串行化同一任务的执行，使用本地 SQLite 检查点恢复。单次活跃执行预算60秒，模型调用超时最多20秒；人类等待不占用连接，数据库锁等待另受数据库设置限制。
- `app/agent/actions.py` 将具体书目快照、操作者、确认期限和申请回执绑定。借阅变更与操作完成记录在同一 MySQL 事务中提交；同一读者行锁及唯一约束防止并发重复申请。
- `app/agent/mcp_adapter.py` 与 `app/mcp/library.py` 连接相同业务服务。MCP 不包含另一套库存或借阅规则。

MCP 是仅供本项目后端调用的第一方接口，采用 Streamable HTTP。它不是通用第三方 OAuth 登录服务：运行时签发90秒有效的专用凭证，校验签名、签发方、受众及作用域。签名密钥由本地 JWT 密钥进行用途隔离派生，普通 Web 登录 JWT 不可用于 MCP；凭证不进入提示词、检查点或前端。

查询凭证只允许 `search_books`、`get_book`。`submit_borrow_decision` 要求限定到具体操作 ID 和确认决定的凭证，只有已通过用户确认的固定执行节点才签发，模型工具列表不包含此工具。MCP 再校验操作所属用户和实时业务规则。以后接入第三方客户端时，应另行设计标准授权流程。

当前 SQLite 检查点方案面向本地单 API 实例，不宣称支持多机部署。执行租约有效期3分钟，进程突然退出后需等租约到期再恢复。并发规模、共享检查点、自动数据保留清理策略属于后续部署工作。

## API

所有接口要求当前登录用户；服务端重新核对任务归属。沿用项目响应格式，须同时检查 HTTP 状态和响应体 `code`。

| 方法与路径 | 参数 | 作用 |
| --- | --- | --- |
| `POST /api/agent/runs` | `request_id`（UUID）、`query` | 幂等创建查找任务 |
| `GET /api/agent/runs/{run_id}` | 无 | 查看任务进度或回执 |
| `POST /api/agent/runs/{run_id}/select` | `book_id` | 选择本次查询返回的书目 |
| `POST /api/agent/runs/{run_id}/decision` | `action_id`、`confirmed`（布尔） | 确认或取消本次具体操作 |
| `POST /api/agent/runs/{run_id}/retry` | 无 | 恢复未完成执行，不跳过人工暂停 |

## Harness 与测试

基础 Harness 已包含工具白名单、严格参数、调用预算、确认绑定、事务回执、持久恢复和故障注入测试。运行时日志事件包含任务编号、操作及调用计数，不打印密钥或原始模型响应；实际日志是否显示取决于服务日志级别。此版没有上线自动评分平台或外部追踪服务。

独立离线验证命令（`backend` 目录）：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_agent.py
# 可选保存不含凭证的结果，目录需已存在
.\.venv\Scripts\python.exe scripts/evaluate_agent.py --output .\data\agent-harness.json
```

该命令强制使用隔离 SQLite、假模型决策和测试身份，执行19项契约测试，不访问业务数据库或云端模型。覆盖只读约束、非法参数、账号停用、工具预算、工具故障、进程重建后的检查点恢复、人工确认、取消、过期、跨用户访问、书目变化、事务回滚、提交后响应丢失恢复和实际 MCP 协议调用。通过率只代表这些确定性场景，不是模型理解准确率。

MySQL 并发测试沿用 [实体图书指南](books-guide.md#自动测试与复验) 的隔离临时库机制，新增两个并发 Agent 确认返回同一申请回执的用例。不要把 SQLite 测试当作 MySQL 锁行为验证。

## 2026-10-16 本地验收

- 全量后端266项（包含真实 MySQL 和 Chroma 测试）、前端25项与生产构建通过；构建保留既有大资源包提示。
- 实际调用本地所配 DeepSeek，经 MCP 查询明确标注的合成书目，选择、确认后创建一条 `pending` 申请；重复确认回执一致，库存保持1册。
- 浏览器真实点击完整链路，验证选择阶段无借阅写入、刷新恢复待确认卡片、提交后恢复回执。1440px 桌面和390px手机截图检查通过，无页面横向溢出或脚本错误。
- 初次浏览器验收因前端服务未运行失败，启动前端后复验通过。所有验收申请最终取消，合成书目下架，合成副本退役；保留流转历史。
- 本机详细结果和截图保存在 Git 忽略的 `backend/data/agent-acceptance/`。验收没有更改既有账号密码或提交密钥，也没有推送 Git。

这证明首条借阅链路和关键故障恢复可运行；尚未完成大规模真实用户问法评测。当前搜索基于书名、作者、ISBN 的关键词匹配，不宣称支持任意语义主题推荐。
