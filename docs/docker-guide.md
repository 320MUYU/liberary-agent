# Docker 本机部署

本方案面向单机演示与开发验收。浏览器入口为 **http://localhost:18081**，仅绑定本机回环地址。使用迁移前的账号和密码登录；不重新初始化管理员，不改变原有账号密码。

## 服务与数据

Docker Compose 项目名固定为 `lab-agent-local`，与其他项目隔离。

| 服务 | 运行方式 | 持久数据 |
| --- | --- | --- |
| web | Node 构建后的静态页面，由 Nginx 提供 | 镜像内静态产物 |
| api | Python 3.13 / FastAPI，单进程 | `app_data`、`uploads` |
| mysql | MySQL 8.0 | `mysql_data` |
| chroma | Chroma 1.5.9 | `chroma_data` |
| worker | 独立知识索引进程 | 与 API 共享 `app_data` |
| mcp | 带能力凭证的内部 MCP 服务 | 与 API 共享 `app_data` |

实际卷名带 `lab-agent-local_` 前缀。数据库、Chroma、API 和 MCP 均不发布宿主机端口。Nginx 同源代理 `/api/`、`/uploads/`，并处理 Vue history 路由刷新；知识原文目录不公开。全部服务使用 `Asia/Shanghai` 时区。

API 的健康检查验证 HTTP 和数据库；MySQL 验证认证查询；Chroma 验证 heartbeat；MCP 验证携带凭证的协议初始化和工具列表；Nginx 验证 `/healthz`。worker 为持续进程，其退出由重启策略恢复；不将进程存活宣称为索引任务处理成功。

## 首次迁移

要求 Docker Desktop 运行 Linux 容器、Compose 支持 `env_file.format: raw`（2.30 及以上），本机现有后端环境和 MySQL 可用。首次构建需要联网拉取镜像、Python 与 Node 依赖。

在仓库根目录的 PowerShell 中执行：

```powershell
./infra/docker/prepare.ps1
./infra/docker/compose.ps1 build api web
./infra/docker/compose.ps1 pull mysql
./infra/docker/migrate.ps1
./infra/docker/compose.ps1 up -d --wait --wait-timeout 180
```

`prepare.ps1` 将本机已验证配置复制到私有 `infra/docker/backend.env`，生成独立的数据库密码及 `infra/docker/.env`。模型密钥、模型参数及原 JWT 签名密钥保留，数据库和服务地址改成 Compose 服务名。配置值通过 raw env 文件传入，避免 `$` 被 Compose 插值。现有私有配置不覆盖；两个配置只存在其一时中止。该完整服务组合要求 `RAG_ENABLED=true`，与本机当前配置一致。

这些配置、备份和运行数据均已忽略，不进入 Git 或镜像。不要输出完整 `docker compose config` 到日志；校验使用 `config --quiet`。

`migrate.ps1` 精确匹配本仓库的 API、MCP、worker 和 Chroma 进程并暂停，保留编辑器、原 MySQL 及其他项目服务。随后生成 SQL 快照，复制知识原文、上传目录和 Chroma 数据，并通过 SQLite backup API 保存 Agent 检查点。原工作区的其他评测文件、日志和本机配置继续保留在原位置；AI 审核报告及人工判断随 MySQL 迁移。

备份位于 `backend/data/docker-backups/<时间戳>/`，包含 `database.sql`、三个卷归档及 `manifest.json`。恢复前检查目标卷和目标数据库为空，拒绝覆盖已有数据；校验归档成员路径、备份文件哈希及恢复后哈希。失败时原数据和快照保留，目标卷可能为未完成状态，不能将失败视为迁移成功。

首次恢复后、业务验收写入前，使用实际备份路径核对所有表和向量数量：

```powershell
./infra/docker/verify.ps1 -Snapshot ./backend/data/docker-backups/<时间戳>
```

如备份已生成但恢复尚未开始，可针对空目标恢复：

```powershell
./infra/docker/migrate.ps1 -RestoreFrom ./backend/data/docker-backups/<时间戳>
```

## 日常启动、停止与更新

```powershell
# 启动已有部署；数据卷和账号保留
./infra/docker/compose.ps1 up -d --wait --wait-timeout 180

# 查看状态及最近日志
./infra/docker/compose.ps1 ps
./infra/docker/compose.ps1 logs --tail 80 api worker mcp

# 停止并移除本项目容器、网络，保留全部数据卷
./infra/docker/compose.ps1 down

# 更新代码或 Docker 配置后，重建并启动
./infra/docker/compose.ps1 build api web
./infra/docker/compose.ps1 up -d --wait --wait-timeout 180
```

本次迁移已经完成，日常启动无需重跑 `migrate.ps1`。更新涉及已有表结构时，先安排备份并执行相应增量升级脚本；`create_all` 只创建缺失表，不升级既有列。SQLite 检查点继续只支持单 API 实例，不增加 API 副本或 Uvicorn worker 数量。

`down -v` 会删除数据卷，不用于停止服务。首次迁移快照不是持续备份：后续 Docker 新增数据应另行备份 MySQL 及四个卷，并保留配套私有配置，确认恢复可用后再做破坏性操作。

## 密码更新后的登录失效（2026-10-18）

用户修改密码或管理员重置密码时，密码与 `users.token_version` 在同一事务中更新，旧 Token 在后续鉴权请求中返回 HTTP 401。前端收到 401 后清除登录状态并跳转登录页；用户需使用新密码重新登录。其他账号不受影响，失败的密码更新不撤销登录。已通过鉴权并正在执行的请求不会被追溯取消。

升级前签发的 Token 没有版本字段，按版本 0 兼容；账号首次更新密码后，这些旧 Token 同样失效。版本必须为非负整数，不能以字符串、布尔值或空值代替。MySQL 行锁串行化同一账号的密码更新，防止并发重置丢失版本递增，也防止两个已鉴权请求同时使用旧密码改密。

已有数据库需要执行一次增量升级，`create_all` 不会给旧表补列。**本机 Docker 库已完成本次升级，日常启动不必重做。** 其他旧部署可按下面顺序操作；备份含账号及业务数据，应保存在已忽略的私有目录中。以下命令在仓库根目录的 PowerShell 执行：

```powershell
./infra/docker/compose.ps1 build api
./infra/docker/compose.ps1 stop web api worker mcp

$tokenBackup = "backend/data/token-version-upgrade/$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Path $tokenBackup
docker exec lab-agent-local-mysql-1 sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump -u "$MYSQL_USER" --single-transaction --no-tablespaces --hex-blob --default-character-set=utf8mb4 "$MYSQL_DATABASE" > /tmp/user-token-before.sql'
if ($LASTEXITCODE -ne 0) { throw '数据库备份失败，停止升级' }
docker cp lab-agent-local-mysql-1:/tmp/user-token-before.sql "$tokenBackup/database.sql"
if ($LASTEXITCODE -ne 0) { throw '备份复制失败，停止升级' }
Get-FileHash "$tokenBackup/database.sql" -Algorithm SHA256

./infra/docker/compose.ps1 run --rm --no-deps -T api python scripts/upgrade_user_token_version.py
./infra/docker/compose.ps1 run --rm --no-deps -T api python scripts/upgrade_user_token_version.py --apply
./infra/docker/compose.ps1 run --rm --no-deps -T api python scripts/upgrade_user_token_version.py
./infra/docker/compose.ps1 up -d --wait --wait-timeout 180
```

先预览，应只列出新增非空整数列、默认值为 0 的语句；应用后再次预览应为 `statements: []`。遇到错误先停止后续命令并检查日志。升级不重置密码、不删除记录，也不会把已有非零版本改回 0。原开发数据库与 Docker 库相互独立；如需使用新的源码启动原开发后端，须先备份原库，再在 `backend` 中运行 `.venv/Scripts/python.exe scripts/upgrade_user_token_version.py` 预览及加 `--apply` 执行。

本次验收：Docker 镜像内后端 491 项测试全部通过，无跳过，覆盖独立 MySQL 并发改密、并发重置、旧表升级、旧 Token 兼容、新密码登录、同秒连续改密、异常回滚及账号隔离。升级前后 24 张业务表、1,046 条记录的既有列内容哈希全部一致，原账号密码保持不变；迁移后所有账号版本均为 0。数据库备份、旧容器源码、逐表摘要和测试日志保存在本机 `backend/data/token-version-upgrade/`，不提交到 Git。更新后的登录页面和健康检查返回 200，未登录访问返回 HTTP 401，不存在账号的登录返回业务码 401；六个服务已恢复运行。

## 返回原本机环境

原 MySQL、`backend/.env`、`backend/data` 与 `backend/uploads` 都保留。迁移后原 API、MCP、worker、Chroma 保持暂停，避免用户误用两个独立数据源。需要返回迁移前环境时，先停止 Docker 部署，再按原 README 在各自终端启动：

```powershell
./infra/docker/compose.ps1 down
cd backend
.venv/Scripts/chroma.exe run --path ./data/chroma --host 127.0.0.1 --port 8001
# 其他终端也在 backend 目录
.venv/Scripts/python.exe -m uvicorn app.mcp.library:app --host 127.0.0.1 --port 8002
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/Scripts/python.exe knowledge_worker.py
```

原开发前端仍按 `npm run dev` 启动。Docker 启用后的新增业务不会自动同步回原 MySQL；上述返回方式恢复的是迁移时的数据状态，不包含后续 Docker 写入。

## 本次验收（2026-10-18）

- 初始迁移：24 张 MySQL 表、1,032 条记录；1 个 Chroma 集合、121 条向量；55 个文件。逐表行数、集合向量数及文件哈希均一致。
- 前端 78 项测试通过；前后端 Docker 镜像构建成功。
- Linux 容器后端 476 项测试全部通过，无跳过。MySQL 测试使用随机独立临时库，Chroma 测试使用独立临时进程和目录。测试启动器清除容器特性开关对默认配置测试的影响，不改变实际运行配置。
- 经部署后的 Nginx 验证注册登录、权限、馆藏及空间查询、上传文件、history 路由刷新、完整借还、预约审批与取消。
- 真实模型经 MCP 完成验收书目检索、选择、明确确认与重复确认幂等；新增申请随后取消。
- 固定题“华科入馆须知允许带大件行李或易燃易爆物品吗？”命中知识并返回来源。首次宽泛提问未满足引用检查，不能将本次链路验收解释为全部馆规问答均已准确。
- 完整移除并重建六个容器与网络后，登录、借还及预约历史、上传文件、Agent 检查点与已完成的统一会话恢复通过。最终镜像核实未包含私有环境文件。
- 验收仅使用 Docker 中新建的专用账号、书目和空间；原数据库逐表行数再次核对仍为 1,032 条。专用记录保留历史，结束后停用账号、下架书目并将空间置为维护。

可复用验收脚本位于 `infra/docker/acceptance.py`，仅允许向容器服务名 `mysql` 指向的数据库写入。`business` 创建专用记录，`live-ai` 调用真实模型并产生费用，`recovery` 复核重启恢复，`cleanup` 停用验收资源。私有验收状态位于 `app_data` 卷的 `docker-acceptance/state.json`，含测试凭证，不公开或提交。
