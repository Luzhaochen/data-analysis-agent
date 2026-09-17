# orders 订单主表

- 用途：每笔订单的成交金额、状态、渠道与促销归属；回答「GMV 多少 / 订单量 / 促销与自然期对比」类问题
- 粒度：一行 = 一个订单；唯一键 order_id；与 order_items 是 1:N（一个订单可含多行明细）
- 时间字段：order_dt（DATE，覆盖 2025-01-01 ~ 2026-08-31）；**所有查询必须带 order_dt 过滤**。
  大促日支付可能跨天（pay_dt），口径统一归属按下单日 order_dt。
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
| order_id | BIGINT | 订单号 | 唯一 | 与明细表关联键 |
| user_id | BIGINT | 下单用户ID | — | 关联 users |
| order_dt | DATE | 下单日期（分区/时间过滤字段） | — | 所有查询必须过滤 |
| pay_dt | DATETIME | 支付时间 | 大促日可能跨天 | 口径归属按下单日 |
| pay_amt | DECIMAL(12,2) | 实付金额 | = 明细 gmv 合计（可对账） | GMV 分母字段；cancelled 为 0 |
| item_cnt | INT | 订单明细行数 | — | 与 order_items 行数一致 |
| order_status | VARCHAR(16) | 订单状态 | completed=完成 cancelled=取消 refunded=已退 | 金额口径必须过滤 cancelled |
| channel | VARCHAR(16) | 下单渠道 | app / pc / miniprogram；**2025-06 前为 NULL** | 按渠道分析需限日期或剔 NULL |
| promo_id | BIGINT | 参与促销活动ID | **NULL = 自然期订单** | 关联 promo_calendar |

- 指标口径：
  - GMV（**默认**·下单口径）：SUM(pay_amt)（order_status <> 'cancelled'）——含 refunded（退款订单曾成交）
  - 净成交额（完成口径）：SUM(pay_amt)（order_status = 'completed'）——严格已完成，排除退款；
    行业参考：部分平台（如淘宝）的「已完成订单」按此严格口径，做外部对比时注意口径对齐
  - 有效订单量：COUNT(*)（order_status <> 'cancelled'）；完成订单量：COUNT(*)（= 'completed'）
  - 客单价：GMV / 订单量（与所取 GMV 口径配套，口径必须一致）
  - 自然期 GMV：SUM(pay_amt)（order_status <> 'cancelled' AND promo_id IS NULL）
- 注意事项/坑：
  - 一个订单可含多 SKU → 与 order_items 关联聚合必须先按 order_id 去重（或先聚合再 JOIN）
  - channel 在 2025-06 前为 NULL（历史字段缺失）→ 按渠道分析必须限定 order_dt >= '2025-06-01' 或显式剔除 NULL
  - pay_amt 应与明细 gmv 合计一致，但存在 2 条 price 漂移脏数据（对账差额 694,302.84 元）
    → 对账差异要先定位到脏数据，不要直接当成口径错误
  - cancelled 订单 pay_amt = 0 且无 pay_dt → 金额口径漏过滤会把 0 摊薄均值
  - 业务对话中的「已完成」有歧义 → 严格 = completed（排除退款）；团队默认口径 = <> cancelled（含退款）。
    用户未指明时按默认口径执行，但展示 SQL 时必须说明口径并询问（行业参考：淘宝「已完成订单」按严格口径）
  - pay_dt 跨天 → 按支付时间统计会与按下单日统计不一致，团队口径统一按下单日
- 常用过滤：
  - `order_status <> 'cancelled'`（金额类指标口径）
  - `promo_id IS NULL`（自然期订单）
  - `order_dt >= '2025-06-01'`（需要渠道字段的场景）
- 关联键：
  - user_id → users.user_id（N:1，取用户属性）
  - promo_id → promo_calendar.promo_id（N:1；NULL 不参与关联，LEFT JOIN 保自然期）
  - order_id ← order_items.order_id（1:N；跨表聚合先去重）
