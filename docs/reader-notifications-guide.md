# 读者站内消息通知

读者从右上角铃铛查看最近五条消息，或从“消息通知”进入完整列表。列表支持分页、只看未读、单条已读和全部已读；点击“查看详情”会打开该账号的最新借阅或预约记录。管理员继续使用原来的分类待办铃铛。

## 通知范围

| 触发条件 | 通知 |
| --- | --- |
| 管理员通过或驳回预约 | 预约结果、空间、时段及审核说明 |
| 管理员确认借出 | 图书和应还时间 |
| 管理员驳回借阅 | 图书及驳回原因 |
| 管理员确认收到归还的实体书 | 归还完成 |
| 借阅进入应还时间前 72 小时至应还时间 | 到期提醒一次 |
| 当前时间晚于应还时间 | 逾期提醒一次 |

提醒仅针对 `borrowed` 状态和启用中的账号。申请归还后即停止生成到期及逾期提醒；历史消息仍保留。取消申请、提交预约、申请归还本身不生成通知。首版不包含邮件、短信或浏览器系统推送。

业务状态与对应通知在同一事务中保存，任何一方失败都会回滚。`(user_id, event_key)` 唯一约束和业务行锁防止并发重复发送。提醒 worker 停止后重新启动时，只发送当前阶段的提醒：已经逾期的借阅不会再补发过期的“三天内到期”消息。升级不补发历史审核消息，既有的在借记录会参与后续提醒。

消息内容记录触发时的信息；详情页显示当前业务状态。通知 ID 与详情 ID 均按登录账号校验归属，其他账号的记录按不存在处理。

## 已读与刷新

已读时间保存在 MySQL，刷新页面及重新登录后继续有效。前端每 30 秒刷新铃铛，隐藏标签页暂停轮询，回到页面时刷新。退出及切换账号会清理通知缓存、定时器，并丢弃旧账号尚未完成的响应。

“全部标为已读”提交列表最后一次加载时的 `max_id`；点击前尚未加载的新通知不会一并标为已读。通知请求失败时显示未更新提示，保留此前的数据，允许手动刷新。

## API

以下接口均要求登录，沿用项目的 `code/message/data` 响应格式。

| 方法及路径 | 用途 |
| --- | --- |
| `GET /api/notifications?page=1&page_size=10&unread_only=false` | 当前账号列表；返回 `items/total/unread_count/max_id` |
| `POST /api/notifications/{id}/read` | 幂等地标记自己的消息已读 |
| `POST /api/notifications/read-all` | 请求体 `{"through_id": 123}`；只处理自己的消息及该边界以内的 ID |
| `GET /api/loans/{id}` | 自己的最新借阅详情，支持通知跳转到列表第一页之外的记录 |

`page_size` 上限为 100；`through_id` 必须是非负整数，不能省略、使用字符串或布尔值。预约详情通过当前账号的预约接口加载。

## 本地开发

新数据库由 API 的 `create_all` 创建 `reader_notifications`。已有数据库先备份，再在 `backend` 目录执行增量脚本：

```powershell
.venv/Scripts/python.exe scripts/upgrade_reader_notifications.py
.venv/Scripts/python.exe scripts/upgrade_reader_notifications.py --apply
.venv/Scripts/python.exe scripts/upgrade_reader_notifications.py
```

第一次预览应只有通知表及索引的创建语句；执行后再次预览为 `statements: []`。脚本要求 `users` 已存在，遇到不兼容的同名表会报错，不覆盖旧表。

与 API 使用相同 `.env`、数据库和时区，另开一个终端运行：

```powershell
.venv/Scripts/python.exe notification_worker.py
# 仅处理一轮后退出
.venv/Scripts/python.exe notification_worker.py --once
```

worker 每 60 秒处理一轮，与知识索引 worker 独立，不要求启用 RAG。每轮分批扫描、逐条重查状态并提交。处理成功后原子更新 `data/notifications/heartbeat.json`；失败不刷新成功时间，下一轮重试。Docker 健康检查要求最近 180 秒内成功完成过扫描，且对应进程存在。

## Docker 更新

入口仍为 `http://127.0.0.1:18081/login`。新增 `notification-worker` 服务，共享 `app_data` 中的心跳目录，消息本身保存在 `mysql_data` 对应的 MySQL 表中。API 仍保持单实例。

先确认 Docker 引擎正常运行，重建镜像并完成隔离测试；暂停业务写入后生成完整数据库备份，核对备份完整性及 SHA256，再执行迁移。以下是完成备份后的升级命令，不代替备份步骤：

```powershell
./infra/docker/compose.ps1 build api web
./infra/docker/compose.ps1 stop web api worker mcp notification-worker
./infra/docker/compose.ps1 run --rm --no-deps -T api python scripts/upgrade_reader_notifications.py
./infra/docker/compose.ps1 run --rm --no-deps -T api python scripts/upgrade_reader_notifications.py --apply
./infra/docker/compose.ps1 run --rm --no-deps -T api python scripts/upgrade_reader_notifications.py
# 复核原业务表内容未改变，再恢复全部服务，包含 web。
./infra/docker/compose.ps1 up -d --wait --wait-timeout 180
./infra/docker/compose.ps1 ps
./infra/docker/compose.ps1 logs --tail 40 notification-worker
```

迁移只新增通知表，不改账号、借阅、预约或其他既有表。确认 `notification-worker` 健康后，使用专用验收账号检查一条新审批通知及已读操作。日志、数据库备份、测试账号凭据不提交到 Git。

## 本次验证与部署状态（2026-10-19）

- 前端 88 项行为测试、Prettier 检查和生产构建通过。
- 后端完整 511 项测试全部通过，无跳过，包含本机随机独立 MySQL 临时库及临时 Chroma 进程；其后新增的一项 MySQL 通知迁移回归也已单独通过。
- 使用独立 SQLite 合成数据及真实 FastAPI/生产前端，系统 Edge 浏览器的 17 项桌面和手机检查通过，无脚本异常。覆盖铃铛、分页、单条及全部已读、刷新保留、未读筛选、借阅与预约最新详情、跨页借阅、退出/账号切换及管理员待办。手机 390 × 844 无横向溢出，长通知弹层可滚动。
- 通知 MySQL 专项 3 项通过：双 worker 去重、旧快照遇到归还申请时不发送提醒、增量迁移重复执行且保留既有账号。测试仅使用随机命名的独立临时库。
- Docker Compose 配置校验通过。**本轮尚未升级本机 Docker 业务库或部署新镜像。** Docker Desktop 被 Windows 遗留通信 socket 的访问错误阻断，按项目三次修复上限停止重试，等待本机环境恢复。没有重置或删除数据库、数据卷及镜像。
- 私有回归日志、截图、环境错误日志和后续备份/部署脚本位于本机 `backend/data/reader-notifications/`，被 Git 忽略。浏览器检查使用的临时站点不是日常部署入口。
