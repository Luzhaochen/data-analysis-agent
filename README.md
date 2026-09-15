# DataAnalysis 数据分析智能体（Claude Code 插件）

以 Claude Code 插件形态实现的数据分析智能体：**知识库驱动 SQL 生成 + 会话结束自进化**。
基于京东大家电风格的模拟数据，全链路可复现、带「已知答案」，可直接用于回归评测。

> 核心理念：智能体好不好用，核心在 memory 知识库与自进化——把常用表、常用字段、
> SQL 片段、语法规则沉淀为知识；会话结束时把跑通的 SQL 和确认过的口径写回知识库。

## 当前进度：Phase 0（环境与模拟数据）✅ · Phase 1（确定性执行层）✅

### 模拟数据：8 张表（京东大家电风格）

`categories / products / users / orders / order_items / promo_calendar / traffic / refunds`

- 2025-01-01 ~ 2026-08-31，28.7 万订单 / 45.9 万明细行
- **确定性生成**（seed=42）：任何人运行得到相同数据与相同「已知答案」，见 [mock_data/known_answers.md](mock_data/known_answers.md)
- 内置业务故事：促销密度 33.7%→71.3%、促销 GMV 占比 43.2%→59.6%、总 GMV 同比 -1.8%、B 级活动高频低效、2026 大促恢复期被高频促销打断
- 内置 5 类脏数据陷阱（时间矛盾 / 单位漂移 / 归属漂移 / 关联丢行 / 历史字段缺失），用于结果校验教学

### 快速开始

```powershell
# 1. 建库建表（root 执行，也可在 MySQL Workbench 里依次执行文件）
mysql -u root -p < mock_data/schema.sql        # 自动建库 + 8 张表
copy mock_data\setup.sql.example mock_data\setup.sql  # 复制后改成你的密码
mysql -u root -p < mock_data/setup.sql         # 只读账号 data_agent
copy config\connection.ini.example config\connection.ini  # 复制后填入 data_agent 密码

# 2. 生成数据（约 1-3 分钟；root 密码交互输入，不进命令行/日志）
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python mock_data\gen_mock_data.py

# 3. 体检（对照已知答案）
.venv\Scripts\python mock_data\check_data.py
```

### 安全约定

- 数据账号最小权限：`data_agent` 仅 SELECT
- `setup.sql`、`connection.ini` 在 .gitignore 中，绝不上传（模板见 `setup.sql.example`）
- 生成器入库时 root 密码通过 getpass 交互输入

## Phase 1：确定性执行层

三个确定性脚本 + 共享客户端——程序负责执行，语义判断留给 SKILL.md 工作流（Phase 3）：

| 文件 | 对应框架步骤 | 职责 |
|---|---|---|
| `_lib/database_client.py` | 共享客户端 | 读配置、统一建连（只读事务兜底）、JSON/CSV/表格三种输出、异常统一包装（绝不让 traceback 裸奔） |
| `skills/database-query/scripts/execute_query.py` | Step 4 | 单语句/只读白名单检查、自动 LIMIT（+1 探测截断）、EXPLAIN dry-run、错误四分类 + 修复建议、retry_log 留痕 |
| `skills/database-query/scripts/get_metadata.py` | Step 2 辅助 | information_schema：表/字段/索引/近似行数 |
| `skills/database-query/scripts/doc_table.py` | 建档骨架 | 用 schema COMMENT 自动生成表文档草稿（语义留「待补充」，审阅后落库） |

**错误四分类**（MySQL 错误码 → 分类 + 建议）：

| error_type | 触发示例 | 应对 |
|---|---|---|
| PARTITION_ERROR | 日期值格式错（1525/1292）、分区越界（1526） | 检查时间过滤写法 |
| FIELD_ERROR | 字段不存在（1054）、表不存在（1146） | 调 get_metadata.py 拿真实 schema |
| SYNTAX_ERROR | 语法错（1064）、ONLY_FULL_GROUP_BY（1055） | 对照 memory/sql_syntax.md |
| PERMISSION_ERROR | 权限拒绝（1142）、写语句被策略拦截 | 不重试，明确告知 |

另有 CONFIG / CONNECTION / TIMEOUT 三类基础设施错误。每次尝试（成功或失败）写入
`runs/<session_id>/retry_log.json`（Step 4 证据留痕，重试上限 retry_max=3 由工作流计数）。

```powershell
# 常用调用
.venv\Scripts\python skills\database-query\scripts\get_metadata.py --brief
.venv\Scripts\python skills\database-query\scripts\execute_query.py --sql "SELECT order_status, COUNT(*) n FROM orders GROUP BY order_status"
.venv\Scripts\python skills\database-query\scripts\execute_query.py --dry-run --sql "SELECT * FROM orders o JOIN order_items i ON o.order_id=i.order_id"
.venv\Scripts\python skills\database-query\scripts\doc_table.py --table refunds   # 草稿 → runs/drafts/
```

## 路线图

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 环境与模拟数据 | ✅ |
| 1 | 确定性执行层（execute_query / get_metadata / doc_table，错误四分类） | ✅ |
| 2 | 知识库（表知识 / SQL 片段 / 语法规则，模板化） | |
| 3 | 主编排 SKILL.md（意图解析→知识检索→SQL→校验→解读→自进化） | |
| 4 | Hooks 自进化兜底（会话结束沉淀） | |
| 5 | 回归评测（用例 + EXPLAIN dry-run） | |
| 6 | 运行产物与安装分发 | |
| 7 | 打磨与面试包装 | |

## 目录结构

```
requirements.txt       # Python 依赖（pymysql）
config/               # 连接与约定配置（connection.ini 本地文件，在 .gitignore 中）
  connection.ini.example   # 连接配置模板
  analysis.json            # 行数上限/超时/只读开关
_lib/
  database_client.py       # 共享客户端：建连/输出/错误四分类
skills/database-query/scripts/
  execute_query.py         # Step 4 SQL 执行入口（含 retry_log 留痕）
  get_metadata.py          # 元数据查询（表/字段/索引/近似行数）
  doc_table.py             # 表文档草稿建档（草稿进 runs/drafts/）
mock_data/             # Phase 0 交付物
  schema.sql           # 自动建库 + 8 张表 DDL（表/字段 COMMENT 即知识库草稿）
  setup.sql.example    # 只读账号初始化模板（复制为 setup.sql 使用）
  gen_mock_data.py     # 确定性模拟数据生成器（seed=42）
  check_data.py        # 数据体检：对照已知答案
  known_answers.md     # 已知答案（业务故事 + 脏数据陷阱）
```

后续 Phase 的 `hooks/`、`eval/` 等目录随各 Phase 提交。
