# promo_calendar 促销日历表

- 用途：促销活动的等级、类型与区间；回答「促销效果对比/活动等级分析/促销密度与自然期挤压」类问题
- 粒度：一行 = 一个促销活动；唯一键 promo_id；与 orders 是 1:N（一个活动覆盖多笔订单）
- 时间字段：start_dt / end_dt（活动区间，含首尾）——**语义与 orders.order_dt 不同**：
  本表区间只用于日历展示与活动筛选，**订单的时间过滤仍用 orders.order_dt**；
  订单的活动归属用 orders.promo_id 精确关联（见坑 1），禁止按日期区间 JOIN
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
| promo_id | BIGINT | 促销活动ID | 唯一（自增） | 订单归属键 |
| promo_name | VARCHAR(64) | 活动名称 | — | — |
| level | CHAR(1) | 活动等级 | S / A / B（本库 5 / 7 / 53 个） | 等级效果对比维度 |
| promo_type | VARCHAR(32) | 活动类型 | 平台大促/品类促销/品牌日 | — |
| activity_theme | VARCHAR(64) | 活动主题 | 如 年货节/品类轮动 | 对齐真实活动日历字段 |
| start_dt | DATE | 开始日期（含） | — | 与 end_dt 组成活动区间 |
| end_dt | DATE | 结束日期（含） | — | 区间可能重叠（见坑 1） |
| duration_days | INT | 活动天数（含首尾） | 真实导出中可能是字符串（如 '1小时'） | 接入时需清洗（见坑 2） |

- 指标口径：
  - 活动 GMV：SUM(orders.pay_amt)（orders.promo_id = 本表 promo_id AND order_status <> 'cancelled'）
  - 活动日均 GMV：活动 GMV / duration_days（**对比不同时长活动必须用日均，见坑 3**）
- 注意事项/坑：
  - 活动区间可能重叠 → 订单归属以 orders.promo_id 为准（数据生成时已指定），
    禁止 `start_dt <= o.order_dt <= end_dt` 的方式 JOIN——会把一笔订单算进多个活动
  - duration_days 在真实数据源中可能混入字符串（如 '1小时'）→ 接入时先清洗为 INT
    （真实踩坑：业务方导出的活动日历字段格式可能不统一）
  - B 级活动高频低效（2026 年 53 个 B 级活动，日均 GMV 133 万 vs 2025 年 249 万）
    → 按等级对比效果必须看日均而非总量，否则活动数量差异会误导结论
  - 促销密度 2025H1 33.7% → 2026H1 71.3% → 同比分析必须区分促销期/自然期
    （orders.promo_id IS NULL），混在一起看不出自然增长的真相
- 常用过滤：
  - `level = 'B'`（只看 B 级活动）
  - `promo_type = '平台大促'`（按类型筛）
  - `start_dt >= '2026-01-01'`（某时间后的活动，仅用于日历筛选）
- 关联键：
  - promo_id → orders.promo_id（1:N；orders 侧 NULL=自然期，LEFT JOIN 保留自然期订单）
