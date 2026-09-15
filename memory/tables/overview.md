# 表索引（overview）

> 检索链第一跳：只回答「去哪张表找什么」。保持一屏内读完，本文件不写细节。
> 使用频次由 Phase 4 会话结束 hook 自动累加（初始为 0）。

| 表 | 用途（一句话） | 详情文档 | 使用频次 |
|---|---|---|---|
| orders | 每笔订单的成交金额/状态/渠道/促销归属 | [orders.md](orders.md) | 0 |
| order_items | 订单明细，一行一 SKU 的行级金额 | [order_items.md](order_items.md) | 0 |
| products | 商品名称/品牌/品类归属 | [products.md](products.md) | 0 |
| categories | 品类层级（一级/二级） | [categories.md](categories.md) | 0 |
| users | 用户注册时间/城市/会员等级 | [users.md](users.md) | 0 |
| promo_calendar | 促销活动日历（S/A/B 级、区间可能重叠） | [promo_calendar.md](promo_calendar.md) | 0 |
| refunds | 退款单（退款时间/金额/原因） | ⏳ 未建档——留给自进化演示 | 0 |
| traffic | 流量（一行一天一二级品类） | ⏳ 未建档——留给自进化演示 | 0 |

## 口径速查（跨表高频）

- GMV = SUM(orders.pay_amt) WHERE order_status <> 'cancelled'（按下单日 order_dt 归属）
- 跨表聚合 1:N 关联必须先按「1」侧去重（如 orders 与 order_items）
- 促销归属：promo_id IS NULL = 自然期
