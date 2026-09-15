# order_items 订单明细表

- 用途：订单行级明细（SKU 维度的成交价与成交额）；回答「商品排行/单价分布/与订单主表对账」类问题
- 粒度：一行 = 一个订单中的一行 SKU；唯一键 item_id；与 orders 是 N:1（一个订单多行明细）
- 时间字段：无——明细没有自己的时间；时间过滤一律经 order_id JOIN orders 用
  orders.order_dt（分区过滤约定见 memory/sql_syntax.md）
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
| item_id | BIGINT | 明细行ID | 唯一（自增） | — |
| order_id | BIGINT | 订单号 | — | 关联 orders（N:1） |
| product_id | BIGINT | 商品ID | — | 关联 products |
| qty | INT | 购买数量 | — | 销量分母字段 |
| price | DECIMAL(10,2) | 成交单价（元） | 折后价，**非挂牌价** | 存在 100 倍漂移脏数据（见坑 3） |
| gmv | DECIMAL(12,2) | 该行成交额（元） | = price × qty（行级口径） | 对账基准字段 |

- 指标口径：
  - SKU 销售额：SUM(gmv)；销量：SUM(qty)
  - 成交均价：SUM(gmv) / SUM(qty)（**勿用 AVG(price)**——会被行数权重带偏）
  - 对账：SUM(gmv) 按 order_id 汇总应等于 orders.pay_amt（存在 2 条脏数据例外，见坑 3）
- 注意事项/坑：
  - 行级表 → 与 orders 1:N 关联聚合必须先按 order_id 去重（COUNT(DISTINCT order_id)），
    否则订单数/订单口径全部虚增
  - price 是成交单价 ≠ products.list_price → 商品实际售价/折扣分析必须用本表，
    用 products.list_price 对比才有意义
  - 2 条 price×100 漂移脏数据（对账差额 694,302.84 元）→ 单价分布、均价、最大单价
    类分析必须先剔除异常（如 price > 100000 或 gmv 与 orders.pay_amt 对账定位），
    否则均值被拉爆
  - 明细没有状态字段 → cancelled 订单的明细行也在表里；GMV 口径必须 JOIN orders
    过滤 order_status <> 'cancelled'
- 常用过滤：
  - JOIN orders 后：`o.order_status <> 'cancelled'`、`o.order_dt BETWEEN ...`
  - `price <= 100000`（剔除 100 倍漂移脏数据，仅单价类分析需要）
- 关联键：
  - order_id → orders.order_id（N:1，带出订单时间/状态/促销）
  - product_id → products.product_id（N:1，带出商品/品牌/品类）
