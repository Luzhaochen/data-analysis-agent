# SQL 语法与口径规则（MySQL）

> 检索链第五跳 + 错误修复对照手册：execute_query.py 报 SYNTAX_ERROR / PARTITION_ERROR /
> FIELD_ERROR 时，先按错误码查本文件对应小节，再改 SQL。
> 规则按「出错时查什么」组织，每条规则给 ✓ 正确写法 / ✗ 错误写法对照。

## 1. 分区/时间过滤（对应 PARTITION_ERROR）

- **所有事实表查询必须带时间过滤**：orders 用 `order_dt`、traffic 用 `dt`。
  维度表（categories/products/users/promo_calendar）没有交易时间，过滤在事实表侧做。
- 时间范围用左闭右开区间，避免跨天/边界重复：
  ```sql
  ✓ WHERE order_dt >= '2026-06-01' AND order_dt < '2026-07-01'
  ✗ WHERE order_dt BETWEEN '2026-06-01' AND '2026-06-30 23:59:59'  -- DATE 类型带时分秒无效
  ```
- **禁止在时间字段上套函数**——会废掉索引（orders 有 idx_order_dt）：
  ```sql
  ✓ WHERE order_dt >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
  ✗ WHERE DATE_FORMAT(order_dt, '%Y-%m') = '2026-06'  -- 应改为范围过滤
  ```
- 日期比较统一用 `'YYYY-MM-DD'` 字符串；报 1525/1292（Incorrect DATE value）先查
  比较值格式与字段类型是否匹配。
- 支付时间 pay_dt 可能跨天：口径统一归属按下单日 order_dt（见 tables/orders.md）。

## 2. 聚合与 GROUP BY（对应 SYNTAX_ERROR 1055）

- ONLY_FULL_GROUP_BY：SELECT / ORDER BY 中的非聚合列必须出现在 GROUP BY 中。
  ```sql
  ✓ SELECT order_status, COUNT(*) FROM orders GROUP BY order_status
  ✗ SELECT order_dt, order_status, COUNT(*) FROM orders GROUP BY order_status  -- 1055
  ```
- 标量子查询必须返回 0/1 行（报 1242 是返回了多行）：用聚合（MAX/MIN）或改 JOIN。
- 聚合函数位置错误会报 1111：`WHERE SUM(x) > 1` ✗ → 用 HAVING 或子查询。

## 3. 去重与 1:N 关联（框架「先去重再聚合」）

- 与 1:N 明细表（order_items）关联时，按「1」侧去重：
  ```sql
  ✓ COUNT(DISTINCT o.order_id)                        -- 订单数
  ✗ COUNT(*)                                          -- 会数成明细行数
  ```
- 跨表聚合优先「先聚合再 JOIN」：
  ```sql
  ✓ JOIN (SELECT order_id, SUM(gmv) s FROM order_items GROUP BY order_id) t
  ✗ JOIN order_items 后直接 SUM  —— 中间结果行数爆炸、口径易错
  ```
- 关联键以 tables/*.md 的「关联键」节为准，不猜字段名。

## 4. 字段与表名（对应 FIELD_ERROR）

- 字段/表名以 `get_metadata.py` 的真实 schema 为准，不凭记忆猜（报 1054/1146 先查 metadata）。
- 多表 JOIN 中同名字段必须加表前缀（报 1052 歧义）：
  ```sql
  ✓ ON o.order_id = oi.order_id   -- 用别名 o/oi，全 SQL 一致
  ```
- 值/类型不匹配（1292/1525 非日期类）：确认比较值类型与字段一致
  （如 `vip_level = '1'` ✗ → `vip_level = 1` ✓）。

## 5. LIMIT 约定

- 脚本自动追加 LIMIT（默认 1000，硬上限 10000）；无需手写 LIMIT 除非要更小窗口。
- 大结果先聚合再取数：需要明细时先缩小时间范围。
- 探针约定：脚本用 LIMIT n+1 探测截断，返回结果带 truncated 标记，照常解读即可。

## 6. 只读与权限（对应 PERMISSION_ERROR）

- 本环境 data_agent 仅 SELECT；INSERT/UPDATE/DDL 一律被策略层或权限层拒绝（1142/1792）。
- 报权限错**不重试**：写操作请用户用 root 在 Workbench 手工执行。

## 7. 性能约定

- 超时（3024）：缩小时间范围、先聚合再取明细；确需更长才调 config/analysis.json 的 timeout_s。
- 改 SQL 前先 `--dry-run` 跑 EXPLAIN，确认走对索引（orders 主过滤索引 idx_order_dt）。
- 连接中断（2013）：可能是查询过慢触发兜底超时（缩小范围），也可能是连接被外部终止
  （重试一次即可，重试会新建连接）。

## 8. 口径速记（跨表高频，与 tables/overview.md 一致）

- GMV = SUM(orders.pay_amt) WHERE order_status <> 'cancelled'（归属按下单日 order_dt）
- 成交均价 = SUM(gmv) / SUM(qty)，**勿用 AVG(price)**
- 促销/自然期拆分：promo_id IS NULL = 自然期；活动归属用 promo_id，禁止按日期区间 JOIN
- 渠道分析：channel 仅 2025-06 起有值，需加 `order_dt >= '2025-06-01'` 或显式剔 NULL
