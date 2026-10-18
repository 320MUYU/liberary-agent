# 华中科技大学图书馆公开资料评测集

本目录是阅见简历项目的外部参考语料，不代表华中科技大学图书馆授权系统、实际馆藏或实时预约服务，也不作为阅见本系统的办理政策。

资料从 `https://lib.hust.edu.cn` 的公开文章接口逐篇采集。`sources.json` 保存可在浏览器打开的原文链接、采集时间和规范化文字快照的 SHA256。快照仅去除 HTML 排版并保留表格列关系；不补写规定，不识别图片中的文字。原始 JSON、原始响应哈希、页面创建/更新字段与图片遗漏数保存在本地 `backend/data/hust-library-acceptance/capture-report.json`，不提交凭证或浏览器运行数据。

八份资料：规章制度、校园卡在图书馆使用管理办法、各类读者借书权限、图书外借服务、图书预约、图书续借、图书馆座位网络预约规则、图书馆座位预约管理办法。图书预约中的二维码及座位管理中的三张图没有纳入文字证据。办事指南中的纯图片流程没有纳入本批次。

官网接口本次没有给出明确的 `publishTime`，因此发布时间和生效日期均保留为空。页面创建、更新、采集时间不等于制度生效日期；座位管理正文包含试运行背景，不能用它认定原馆今天的开闭馆或实时容量。

## 题目与验收边界

- `calibration.json`：20题，用于排查和调整。
- `validation.json`：30题，在真实执行前冻结；编号、问题和主要事实组与调参集分开。验证集上的失败作为结果保留，不能调参后仍宣称同一份验证集为全新独立验收。
- 共42道有依据题与8道应拒答题；覆盖直接问法、同义表达、多轮追问、跨章节、范围冲突和要求编造引用的指令。
- 问题和参考事实由开发代理依据原文辅助编写，**不是收集到的真实读者问题，也没有完成独立人工标注审核**。`annotation_review=pending_human` 必须保留到人工审核完成。
- 每题的引用摘录经过脚本检查，必须存在于固定哈希的原文快照中。有多份等价规则时使用 `expected_source_groups` 表示可替代证据，避免把引用另一份同等官方证据误计为漏检。
- 检索 Recall@4 按预期相关文档计算；回答证据覆盖按必须满足的证据组计算。它们不等于答案事实正确率。现有语料规模小，不用于推断全校真实问法或大规模知识库的准确率。
- 正式的人类语义审核通过每次运行独有的报告编号绑定实际答案。未审核前，答案正确率、引用支持率为空；审核表不得用模型判断冒充人工判断。

## 复现

在项目 `backend` 目录执行，使用已安装依赖，不需要新依赖：

```powershell
.venv\Scripts\python.exe scripts/evaluate_library.py check --manifest ../evals/hust-library/sources.json --dataset ../evals/hust-library/validation.json --other-split ../evals/hust-library/calibration.json --snapshot-root ../evals/hust-library/snapshots

# 预览数据库增量与导入，默认不会发布文档
.venv\Scripts\python.exe scripts/upgrade_library_corpus.py
.venv\Scripts\python.exe scripts/import_library_corpus.py ../evals/hust-library/sources.json --snapshot-root ../evals/hust-library/snapshots
```

重新抓取官网时，应输出到新的本地目录并与本次快照比较；不要覆盖已验收报告对应的来源文件。若官方正文变化，须重核题目并建立新的评测版本。

真实入库、模型调用、逐题报告和人工审核的完整命令见 `docs/library-acceptance.md`。
