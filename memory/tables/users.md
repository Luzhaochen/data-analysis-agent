# users 用户维度表

- 用途：用户注册时间、城市与会员等级；回答「新老用户结构/地域分布/会员分层」类问题
- 粒度：一行 = 一个用户；唯一键 user_id；与 orders 是 1:N（一个用户多笔订单）
- 时间字段：register_dt（注册日期）——**只用于切「新用户」口径**；交易行为的时间过滤在
  orders.order_dt 侧做（「某月活跃用户」必须去 orders 找，见坑 1）
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
| user_id | BIGINT | 用户ID | 唯一 | 与 orders 关联键 |
| register_dt | DATE | 注册日期 | — | 新用户口径字段（非活跃时间） |
| city | VARCHAR(32) | 所在城市 | 本库 20 个城市 | 地域分布维度 |
| vip_level | TINYINT | 会员等级 | 0=普通 1=银牌 2=金牌 3=钻石 | 当前快照（见坑 2） |

- 指标口径：
  - 本表无业务指标（维度表）——GMV/订单量在 orders 侧；用户级指标（人均 GMV 等）
    先按 user_id 在 orders 聚合，再 JOIN 本表带属性
- 注意事项/坑：
  - register_dt 是注册时间不是活跃时间 → 「2026-06 新用户」= register_dt 在当月；
    「2026-06 活跃用户」必须去 orders 按 order_dt 找，混用两者口径全错
  - vip_level 是当前快照，无历史等级 → 按会员等级分析历史 GMV 时，用的是用户
    「现在」的等级而非下单时的等级，解读时必须说明这一口径限制
  - 与 orders 是 1:N → 用户级聚合（人均 GMV/客单）先聚合再关联，或 COUNT(DISTINCT user_id)，
    直接 JOIN 后 COUNT(*) 得到的是订单数不是用户数
- 常用过滤：
  - `register_dt >= '2026-01-01'`（某时间后注册的新用户）
  - `vip_level >= 1`（付费会员）/ `vip_level = 0`（普通用户）
  - `city = '<城市>'`（地域切分）
- 关联键：
  - user_id → orders.user_id（1:N，用户属性挂到订单）
