# products 商品表

- 用途：商品名称/品牌/品类归属与挂牌价；回答「按品牌下钻/商品价位分析/在售与下架商品」类问题
- 粒度：一行 = 一个商品（SKU）；唯一键 product_id；与 order_items 是 1:N（一个商品出现在多行明细）
- 时间字段：launch_dt（上市日期）——**不是过滤字段**：它不随时间变化、也不等于交易时间；
  交易行为的时间过滤一律在 orders.order_dt 侧做。launch_dt 仅用于「上市时长/新品」类分析
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
| product_id | BIGINT | 商品ID（SKU） | 唯一 | 与订单明细表的关联键 |
| product_name | VARCHAR(128) | 商品名称 | — | — |
| brand | VARCHAR(64) | 品牌 | 本库 27 个品牌 | 按品牌分组用 brand，名称带出即可 |
| category_id | INT | 所属**二级**品类ID | — | 关联 categories（二级行） |
| list_price | DECIMAL(10,2) | 挂牌价（元） | 标价，**非成交价** | 与 GMV 无直接关系（见坑 1） |
| launch_dt | DATE | 上市日期 | — | 时间字段但非过滤字段（见坑 2） |
| is_active | TINYINT(1) | 在售状态 | 1=在售 0=下架 | 本库 45 个 SKU |

- 指标口径：
  - 本表无指标（维度表）——销售额/销量在 order_items（行级 gmv/qty）；list_price 禁止当金额参与聚合
- 注意事项/坑：
  - 挂牌价 ≠ 成交价 → 成交价在 order_items.price、成交额在 order_items.gmv；
    用 list_price 算销售额必错
  - launch_dt 是上市日期，不是交易日期、不随时间变化 → 别把它当分区字段写进
    「最近 N 天销售」类查询；交易过滤用 orders.order_dt
  - 下架商品（is_active=0）仍有历史订单 → 销售分析 JOIN products 时若只取
    is_active=1 会丢下架商品的历史交易；应 LEFT JOIN 或不做状态过滤
  - category_id 是二级品类 → 一级品类口径需经 categories.parent_id 上卷，不能直接汇总
- 常用过滤：
  - `is_active = 1`（只看在售商品）
  - `is_active = 0`（只看下架商品）
- 关联键：
  - product_id → order_items.product_id（1:N，明细行取商品属性）
  - category_id → categories.category_id（N:1，取品类名/上卷）
