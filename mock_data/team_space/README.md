# team_space（模拟团队空间）

> 模拟业务团队的共享文件区。业务方新增数据表后，把建表 DDL 丢进本目录——
> agent 的扫描脚本（hooks/scan_tables.py）会发现新表并生成知识库草稿。
> 对应自进化途径②：定时扫描团队空间发现新表（途径①是会话 hook，见 Phase 4）。

## 使用方式（业务方视角）

1. 在数据库建好新表（root 在 Workbench 执行 DDL，选 `jd_demo` 库）；
2. 把建表 DDL 存成 `.sql` 文件放进本目录（文件名建议 = 表名.sql）；
3. 运行 `hooks/scan_tables.py`（或等定时任务）——新表自动生成建档草稿到 `runs/drafts/`。

## 规则

- 每个 `.sql` 文件放一张表的 CREATE TABLE 即可，脚本按 CREATE TABLE 语句提取表名；
- 本目录的 DDL 只是「新表信号」——schema 事实源是数据库 information_schema，
  草稿字段以数据库实际结构为准（DDL 与库不一致时以库为准）；
- 草稿需人工审阅补充语义后，才进入正式知识库 memory/tables/（人工闸门）；
- 本目录是模拟环境；真实场景中对应团队的共享文档/数据目录。
