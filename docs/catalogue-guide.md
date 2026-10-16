# 公开书目导入与知识库

导入对象是已核对的具体图书版次元数据，不是图书正文，也不代表本馆拥有该书。
来源采用 Open Library 的公开目录；保留版次链接、作品编号和原始语言。中文版本优先，无法核实的中文译名不自行补写。

## 导入约定

- 每条记录必须有版次编号、书名、作者和分类。ISBN 校验通过后统一为 ISBN-13；缺失字段保持空值。
- ISBN、出版社、出版年份、书名来自同一个版次；不能拼接多个版本的字段。
- 人工筛选题材，避免把包含人工智能主题的科幻小说归入 AI 技术书。
- 通过来源版次和 ISBN 检查重复。相同输入重复执行不建新书、不覆盖管理员修改、不重新上架。
- 来源内容发生变化或 ISBN 已属于另一条书目时终止本批次，留给管理员核对，不自动合并。
- 导入不创建实体副本。副本条码、位置及可借状态由管理员按实际馆藏登记。

新增 `book_sources` 表保存来源，不改变既有图书和借阅表。更新后先重启 FastAPI，启动过程会创建缺失的表；不会删除原有数据。

在 `backend` 目录运行：

```powershell
# 先预览已核对的本地 JSON 数组
.\.venv\Scripts\python.exe scripts/import_catalogue.py data/catalogue-import/reviewed.json
# 确认输入后写入
.\.venv\Scripts\python.exe scripts/import_catalogue.py data/catalogue-import/reviewed.json --apply
```

输入字段为 `source_id`、`work_id`、`title`、`author`、`isbn`、`publisher`、`publication_year`、`category`、`languages`、`subjects`。
其中 `source_id` 必须是 Open Library 的 `/books/OL…M` 版次编号；`category` 为 `AI / Agent`、`儿童图书`、`历史图书`。
运行数据存于 Git 忽略的 `backend/data/catalogue-import/`，不含账号密码或模型密钥。

## 同步知识库

先启动 Chroma、索引 worker，并在本地配置中启用 RAG。每本书对应一份以真实书名命名的知识文档：

```powershell
.\.venv\Scripts\python.exe scripts/import_catalogue.py data/catalogue-import/reviewed.json --apply --sync-knowledge
# 等待 worker 索引完成，再运行；只会发布 ready 版本
.\.venv\Scripts\python.exe scripts/import_catalogue.py data/catalogue-import/reviewed.json --apply --sync-knowledge --publish
# 失败版本可在排查原因后显式重试
.\.venv\Scripts\python.exe scripts/import_catalogue.py data/catalogue-import/reviewed.json --apply --sync-knowledge --retry-failed
```

CLI 返回每本书的书目、文档和版本编号及状态。中断后重跑同一文件可继续；不自动轮询、不把 queued 当成 published。
新版本索引完成前保留旧发布版本。相同内容不创建重复版本；被管理员删除的文档不会自动重新创建。
管理员修改或下架书目后，必须重新执行同步，知识库不会自动实时更新；下架书目同步时会停用其关联文档。元数据文档不保存库存快照，实时库存仍由图书接口计算。
同步入口是本机管理员维护工具，不对读者暴露，不要求输入或保存管理员密码。

## 获取数据

针对读者明确提出的主题进行有限查询并缓存结果，先人工筛选，再转换、校验、导入。API 没有返回的字段不由语言模型填补。
大规模目录迁移应使用官方数据下载，不通过 API 遍历整库。参见 [Open Library API](https://openlibrary.org/developers/api) 与 [Search API 版次字段](https://openlibrary.org/dev/docs/api/search)。

## 测试数据清理

2026-10-16 下架了逐一核实的6条本机验收书目，保留全部借阅和副本历史。状态备份位于本地 `data/catalogue-import/test-books-before.json`。读者列表不再显示这些记录。

## 本轮数据与验收记录

2026-10-16 从 Open Library 导入30本具体版次：AI / Agent、儿童图书、历史图书各10本。仅保存书目元数据，不含正文，未创建实体副本。
对应30份知识文档均已发布，共59个切片；逐份核对真实 Chroma 入库记录，与数据库切片一致。

- 全量后端279项测试通过，包含 MySQL 与 Chroma 实际服务测试。
- 前端26项测试及生产构建通过。
- 真实问答验证通过：多智能体相关书目、《夏洛的网》的作者与出版社、《万历十五年》的出版年份；每条回答的引用原文预览均通过。
- 浏览器独立检查通过：真实书目列表、来源详情、馆藏提示、桌面及手机布局，无横向溢出或脚本异常。
- 三个分类各10本由用户手动确认。分类菜单自动检查读取可见项时连续超时，已停止重试，不计为自动化通过。

原始书目、导入结果与验收报告仅保存在 Git 忽略的 `backend/data/catalogue-import/`，不随代码提交。
其中 `live-verification.json` 记录入库和问答结果，`browser-layout-verification.json` 及页面截图记录独立的浏览器检查。本轮三条问答是流程检查，不代表大规模召回率评估。
