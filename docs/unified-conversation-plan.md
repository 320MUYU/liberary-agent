# 统一会话实施计划

用户于 2026-10-18 批准。基线 `38aa212`，分支 `feat/unified-conversation`。
原有四处修改已保存至 `pre-unified-conversation-existing-changes` stash，完成后原样恢复。

沿用 Vue、FastAPI、LangGraph、RAG、MCP，无新增依赖。统一会话保存消息和多个任务，
协调器按本轮需求和服务端历史调度知识、图书、空间专家；普通聊天直接回答。
快捷能力提示不切换会话，所有选择、条件核对、确认和回执出现在消息流中。
身份和业务确认由服务端维护，原业务权限、管理员审核、预算和幂等规则继续生效。

1. 协议和存储：新增 conversation schemas/models、升级脚本及注册；验证严格输入、唯一性、增量升级。
2. 协调器：扩展 coordinator/workflow 协议，新增 conversation 服务；验证历史、追问、澄清、恢复与隔离。
3. 专家：扩展 specialists，复用 ai_services/rag_service；验证来源和必要结果传递、工具隔离。
4. API：新增 conversation API 并在集中路由注册；验证发消息、条件、操作、重复确认和恢复。
5. UI：统一 AssistantView、conversationApi 和消息卡片，复用原业务结果；验证单输入框、多任务和迟到响应。
6. 验收：后端/前端测试、构建及可用的真实模型/MCP/浏览器检查，更新指南与 README。

每个单元先写行为测试，相关检查通过后独立 Conventional Commit，不推送。
相同执行错误最多修复三次；实质变更重新审查。

基线验证：工作流相关后端 24 项和前端 45 项通过。
