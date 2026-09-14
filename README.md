# DataAnalysis 数据分析智能体（Claude Code 插件）

以 Claude Code 插件形态实现的数据分析智能体：**知识库驱动 SQL 生成 + 会话结束自进化**。
基于京东大家电风格的模拟数据，全链路可复现、带「已知答案」，可直接用于回归评测。

> 核心理念：智能体好不好用，核心在 memory 知识库与自进化——把常用表、常用字段、
> SQL 片段、语法规则沉淀为知识；会话结束时把跑通的 SQL 和确认过的口径写回知识库。

## 当前进度：Phase 0（环境与模拟数据）✅

### 模拟数据：8 张表（京东大家电风格）

`categories / products / users / orders / order_items / promo_calendar / traffic / refunds`

- 2025-01-01 ~ 2026-08-31，28.7 万订单 / 45.9 万明细行
- **确定性生成**（seed=42）：任何人运行得到相同数据与相同「已知答案」，见 [mock_data/known_answers.md](mock_data/known_answers.md)
- 内置业务故事：促销密度 33.7%→71.3%、促销 GMV 占比 43.2%→59.6%、总 GMV 同比 -1.8%、B 级活动高频低效、2026 大促恢复期被高频促销打断
- 内置 5 类脏数据陷阱（时间矛盾 / 单位漂移 / 归属漂移 / 关联丢行 / 历史字段缺失），用于结果校验教学

### 快速开始

```powershell
# 1. 建库建表（root 执行，也可在 MySQL Workbench 里依次执行文件）
mysql -u root -p < mock_data/schema.sql        # 8 张表
mysql -u root -p < mock_data/alter_promo.sql   # 活动日历增量列
copy mock_data\setup.sql.example mock_data\setup.sql  # 复制后改成你的密码
mysql -u root -p < mock_data/setup.sql         # 只读账号 data_agent

# 2. 生成数据（约 1-3 分钟；root 密码交互输入，不进命令行/日志）
python -m venv .venv
.venv\Scripts\pip install pymysql
.venv\Scripts\python mock_data\gen_mock_data.py

# 3. 体检（对照已知答案）
.venv\Scripts\python mock_data\check_data.py
```

### 安全约定

- 数据账号最小权限：`data_agent` 仅 SELECT
- `setup.sql`、`connection.ini` 在 .gitignore 中，绝不上传（模板见 `setup.sql.example`）
- 生成器入库时 root 密码通过 getpass 交互输入

## 路线图

| Phase | 内容 | 状态 |
|---|---|---|
| 0 | 环境与模拟数据 | ✅ 本仓库当前内容 |
| 1 | 确定性执行层（execute_query / get_metadata / doc_table，错误四分类） | 进行中 |
| 2 | 知识库（表知识 / SQL 片段 / 语法规则，模板化） | |
| 3 | 主编排 SKILL.md（意图解析→知识检索→SQL→校验→解读→自进化） | |
| 4 | Hooks 自进化兜底（会话结束沉淀） | |
| 5 | 回归评测（用例 + EXPLAIN dry-run） | |
| 6 | 运行产物与安装分发 | |
| 7 | 打磨与面试包装 | |

## 目录结构

```
mock_data/             # Phase 0 交付物
  schema.sql           # 8 张表 DDL（表/字段 COMMENT 即知识库草稿）
  alter_promo.sql      # 活动日历增量列
  setup.sql.example    # 只读账号初始化模板（复制为 setup.sql 使用）
  gen_mock_data.py     # 确定性模拟数据生成器（seed=42）
  check_data.py        # 数据体检：对照已知答案
  known_answers.md     # 已知答案（业务故事 + 脏数据陷阱）
```

后续 Phase 的 `skills/`、`hooks/`、`eval/` 等目录随各 Phase 提交。
