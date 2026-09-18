# DataAnalysis 数据分析智能体（Claude Code 插件）

以 Claude Code 插件形态实现的数据分析智能体：**知识库驱动 SQL 生成 + 会话结束自进化**。
基于京东大家电风格的模拟数据，全链路可复现、带「已知答案」，可直接用于回归评测。

> 核心理念：智能体好不好用，核心在 memory 知识库与自进化——把常用表、常用字段、
> SQL 片段、语法规则沉淀为知识；会话结束时把跑通的 SQL 和确认过的口径写回知识库。

## 当前进度：Phase 0（环境与模拟数据）✅ · Phase 1（确定性执行层）✅ · Phase 2（知识库）✅ · Phase 3（主编排 SKILL.md）✅ · Phase 4（Hooks 自进化兜底）✅ · Phase 5（回归评测）✅

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

## Phase 2：知识库（memory）

**知识库是 agent 的核心**——常用表、常用字段、SQL 片段、语法规则沉淀为 Markdown 知识，
新表随业务出现时由自进化途径自动建档。检索链：overview（表索引）→ 单表详情 →
SQL 片段 → 语法规则（sql_syntax.md）。

| 文件/目录 | 内容 |
|---|---|
| `memory/tables/模板.md` | 单表知识撰写规范：8 节对应模型写 SQL 的 8 个决策点；含草稿模板段（doc_table.py 渲染用，单一事实源） |
| `memory/tables/` | 表索引 overview + 7 张正式表文档（用途/粒度/时间字段/字段口径/指标公式/坑/关联键）；refunds、traffic 故意留白给自进化演示 |
| `memory/sql_syntax.md` | 规则手册：分区过滤/聚合/去重/LIMIT/性能约定——事前预防 + 报错对照双用途 |
| `memory/sql_snippets/` | 实测跑通的 SQL 片段（每日 GMV 趋势 / 促销效果对比），文件头带适用条件与口径说明 |
| `hooks/scan_tables.py` | 自进化途径②：扫描团队空间（mock_data/team_space/）发现新表 → 建档草稿 → 人工审阅落库 |

**两条自进化途径**：

- 途径① 会话 hook（Phase 4）：会话中出现未建档表 → 会话结束触发草稿建档；
- 途径② 团队空间扫描（已落地）：业务方把新表 DDL 丢进 `mock_data/team_space/` →
  扫描发现 → 草稿建档 → 主 Agent 审阅落库（DDL 只是「新表信号」，schema 事实源是数据库）。

```powershell
# 团队空间扫描演示（把新表 DDL 放进 mock_data/team_space/ 后）
.venv\Scripts\python hooks\scan_tables.py
```

## Phase 3：主编排 SKILL.md（提示词工作流）

「手（执行层）+ 大脑（知识库）+ 思维（工作流）」三层架构中的思维层——模型只负责语义决策。

| 文件 | 内容 |
|---|---|
| `skills/analysis/SKILL.md` | 主工作流：意图解析→知识检索→SQL 生成→执行重试→结果校验→解读→自进化六步；5 条硬性规则（未读 overview 不得写 SQL / 五要素不全先澄清 / 口径确认后执行 / 事实以知识库为准 / 环境只读）+ 每步自检清单 |
| `skills/database-query/SKILL.md` | 工具使用约定：四脚本何时用/参数/返回解读/错误标准应对 |

**验收**：11 道业务题迭代测试全过（5 处独立查询交叉对账分毫不差）+ 冷启动验证（新会话
无上下文，7 项行为清单全过、数字与标准答案一致）——见 `runs/phase3-iter/iter_log.md`
与 `docs/Phase3-面试复盘.md`。冷启动会话中模型**独立完成首次自进化**：主动提议并落库
`monthly_conv_rate_comparison.sql`（双写法）+ 同步表文档与口径速查，全部实测跑通。

## Phase 4：Hooks 自进化兜底（途径①）

专业人士指导的自进化途径①（会话 hook）落地——与 Phase 2 的途径②（团队空间扫描）构成闭环：

- `hooks/session_evolution.py`：SessionEnd `--enqueue`（毫秒级入队，适配 1.5s 预算）
  + SessionStart `--process`（使用计数 / 草稿建档 / 幂等 / 进化摘要注入上下文）；
- `.claude/settings.json`：hooks 注册（`${CLAUDE_PROJECT_DIR}` 占位符，机器无关可提交）；
- `hooks/DEBUG.md`：调试笔记（7 个踩坑：1.5s 预算、配置加载时机、计数语义陷阱
  「出现≠使用」→ FROM/JOIN 修正等）。

**两条自进化线并行**：模型按 SKILL.md Step 6 做语义自进化（写文档/片段/落库），
钩子做确定性兜底（使用频次计数/草稿骨架/幂等）。端到端验收：留白表 refunds 被真实
会话触发完整建档（模型落库 + 钩子计数 +1 在同一行协作）。

## Phase 5：回归评测（Eval）

项目的质量保险层——每次改 SKILL.md 或知识库后跑一遍，改坏立现：

- `eval/cases.json`：15 用例（5 基础取数 / 5 口径陷阱 / 3 多步查询 / 1 澄清 / 1 拒绝），
  参考 SQL 全部来自实测跑通的测试，不用 agent 结果当答案；
- `eval/run_eval.py`：确定性 grader（不调 LLM）——知识覆盖检查（overview 有行 +
  详情文档存在 + 指标有口径定义）+ SQL 规则检查（must_have / must_not_have）+
  EXPLAIN dry-run 语法验证；reject 用例断言写操作被策略层拒绝。

```powershell
.venv\Scripts\python eval\run_eval.py            # 全量回归（15/15）
.venv\Scripts\python eval\run_eval.py --case X   # 单用例调试
```

验收：破坏测试双通过（语法错被 EXPLAIN 精确报 1064、表文档缺失被报出文件名）。

## 路线图

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 环境与模拟数据 | ✅ |
| 1 | 确定性执行层（execute_query / get_metadata / doc_table，错误四分类） | ✅ |
| 2 | 知识库（表知识 / SQL 片段 / 语法规则，模板化 + 团队空间扫描） | ✅ |
| 3 | 主编排 SKILL.md（意图解析→知识检索→SQL→校验→解读→自进化，11 题 + 冷启动验收） | ✅ |
| 4 | Hooks 自进化兜底（会话结束沉淀：队列化 + 计数 + 建档 + 幂等） | ✅ |
| 5 | 回归评测（15 用例 + 知识覆盖 + SQL 规则 + EXPLAIN） | ✅ |
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
skills/               # 技能（Phase 3）
  analysis/SKILL.md     # 主工作流（Step 1~6 提示词）
  database-query/
    SKILL.md            # 工具使用约定
    scripts/
      execute_query.py  # Step 4 SQL 执行入口（含 retry_log 留痕）
      get_metadata.py   # 元数据查询（表/字段/索引/近似行数）
      doc_table.py      # 表文档草稿建档（按模板.md 渲染，草稿进 runs/drafts/）
memory/               # Phase 2：知识库（agent 的核心）
  tables/               # 模板 + overview 表索引 + 表文档
  sql_snippets/         # 实测跑通的 SQL 片段
  sql_syntax.md         # 语法与口径规则手册
hooks/
  scan_tables.py        # 团队空间扫描（自进化途径②）
  session_evolution.py  # 会话自进化（途径①：SessionEnd 入队 / SessionStart 处理）
  echo_hook.py          # 最小调试钩子（验证事件触发）
  DEBUG.md              # 钩子调试笔记（踩坑记录）
eval/                  # Phase 5：回归评测
  cases.json           # 15 用例（基础/口径陷阱/多步/澄清/拒绝）
  run_eval.py          # 确定性校验器（知识覆盖 + SQL 规则 + EXPLAIN）
mock_data/             # Phase 0 交付物
  schema.sql           # 自动建库 + 8 张表 DDL（表/字段 COMMENT 即知识库草稿）
  team_space/          # 模拟团队空间（业务方新表 DDL 入口）
  setup.sql.example    # 只读账号初始化模板（复制为 setup.sql 使用）
  gen_mock_data.py     # 确定性模拟数据生成器（seed=42）
  check_data.py        # 数据体检：对照已知答案
  known_answers.md     # 已知答案（业务故事 + 脏数据陷阱）
```

后续 Phase 的 `eval/` 等目录随各 Phase 提交。
