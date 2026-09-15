# inventory 库存快照表

- 用途：各仓库各商品的每日库存快照；回答「缺货预警/补货计划/库存周转」类问题
- 粒度：一行 = 一天一商品一仓库；唯一键 inventory_id；业务唯一组合 (product_id, warehouse, dt)；与 products 是 N:1
- 时间字段：dt（DATE，库存快照日期）——库存指标必须带 dt 过滤；「最新库存」= 每 (product_id, warehouse) 取 MAX(dt) 的快照（见坑 3）
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
| inventory_id | BIGINT | 库存记录ID | 唯一（自增） | — |
| product_id | BIGINT | 商品ID | — | 关联 products |
| warehouse | VARCHAR(32) | 仓库 | 华北仓/华东仓/华南仓/西南仓 | 全国总量 = 各仓汇总 |
| stock_qty | INT | 库存数量（件） | — | 件数，非金额 |
| dt | DATE | 库存快照日期（分区字段） | — | 所有查询必须过滤 |

- 指标口径：
  - 最新库存：WHERE dt = (SELECT MAX(dt) FROM inventory) 的 stock_qty
  - 全国总库存（单日快照）：SUM(stock_qty)（同一 dt 下）
  - 缺货商品：最新快照中 stock_qty = 0 的 (product_id, warehouse)
- 注意事项/坑：
  - 快照表跨天聚合会重复计算 → 总库存必须锁定单日（先取最新快照再聚合），
    不能对多天数据直接 SUM
  - 一个商品在同一快照日最多 4 行（4 个仓）→ 「某商品库存」要 SUM 各仓或
    明确单仓口径，直接取一行会漏仓
  - 业务方不保证每天更新快照（dt 可能跳天）→ 「最新库存」用 MAX(dt) 而不是
    「昨天」，否则跳天时取到过期快照
  - stock_qty 是件数 → 缺货/周转分析用件数；库存金额口径本表未定义，勿用
    products.list_price 折算（那是挂牌价不是成本价）
- 常用过滤：
  - `dt = (SELECT MAX(dt) FROM inventory)`（最新快照）
  - `stock_qty = 0`（缺货）
  - `warehouse = '华北仓'`（单仓视角）
- 关联键：
  - product_id → products.product_id（N:1，带出商品/品牌/品类属性）
