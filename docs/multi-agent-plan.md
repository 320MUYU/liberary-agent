# 多智能体工作流实施计划

用户于 2026-10-17 批准。基线为 `9ae82f8`，开发分支 `feat/multi-agent-workflows`。
已有四处修改保存在 `pre-workflow-existing-user-changes` stash，完成后原样恢复，不混入功能提交。

## 目标与技术

沿用 LangGraph、Pydantic、SQLAlchemy、DeepSeek、local/MCP，无新增依赖。
协调器生成至多三个受约束的步骤，图书与空间专家使用独立子任务、上下文和工具权限。
顺序推进，每次请求只推进一个有界阶段。业务写入逐项选择、确认，管理员审批流程保留。
父任务保存计划、步骤、确定性子任务编号、执行租约与跨重试累计预算。
缺少条件时请求补充；用户确认预约条件后才委派。部分成功保留回执，重试不重做已完成步骤。

## 步骤与验收

1. 基线：保存本地修改、建分支、当前模型/MCP只读冒烟、记录服务状态。
2. 存储：新增 schemas/workflow.py、models/workflow.py、upgrade_agent_workflows.py；注册模型。
   先测严格协议、父子唯一性及增量升级保留旧数据，再实现。
3. 专家：新增 agent/specialists.py，调整 runtime.py、policy.py。
   测工具隔离、独立恢复和父预算累计，保留原接口。
4. 协调器：新增 agent/coordinator.py、agent/workflow.py。
   测计划校验、澄清、顺序委派、确认绑定、部分成功、丢失响应恢复和预算上限。
5. API/UI：新增 api/workflow.py、workflowApi.js、WorkflowAssistant.vue；注册路由及统一入口，复用业务组件。
   测归属、重复操作、刷新恢复、迟到响应及前端构建。
6. 验收：新增 test_workflow_*.py、fixtures/workflows.json、workflowAssistant.test.mjs；扩展 evaluate_agent.py。
   全量后端/前端、MySQL/Chroma、真实模型/MCP和桌面/手机浏览器验收，更新指南与 README。

每个功能单元先写行为测试，验证后单独 Conventional Commit；不推送。
同一错误修复最多三次，仍失败则附日志报告。实质变更需重新审查。

## 基线验证

2026-10-17：后端339项覆盖通过（322项默认通过，另补跑17项MySQL/Chroma通过）；
Agent专项70项、前端39项及生产构建通过。构建有既有大包提示。
最初仅MySQL运行；当前本地模型为deepseek-v4-pro，transport=mcp，RAG及重排启用。
离线测试不代表真实模型工具调用质量。

基线冒烟：真实 `deepseek-v4-pro` 成功生成 `search_books` 调用，MCP返回合法成功结果。
当时Chroma未启动，主题结果为空；仅证明模型工具调用与MCP通信，不作为召回质量验收。
报告位于 Git 忽略的 `backend/data/workflow-acceptance/baseline-smoke.json`。

## 后续范围

知识 Agent、管理员辅助 Agent、共享检查点/多实例、数据保留策略及只读并行列入后续阶段。
首版不自动撤销已提交业务，不把多个业务申请当作单一数据库事务。

## 完成记录（2026-10-17）

六个步骤均已实施并分步提交。最终后端364项（含MySQL/Chroma，无跳过）、离线Harness94项、前端45项、Prettier与生产构建通过。
真实模型/MCP桌面与手机验收通过：两个专家独立查询、逐项选择和确认、刷新恢复、回执重放，6次模型和3次工具调用。
修复真实模型思考模式不支持强制工具选择，以及刷新重新激活跳过步骤两项问题，并加入行为回归。
本机两个工作流表已增量创建，重复升级为空计划。合成申请已取消，合成资源和账号已停用，保留历史。
详细操作和验证边界见 `docs/agent-guide.md` 的组合任务章节。
