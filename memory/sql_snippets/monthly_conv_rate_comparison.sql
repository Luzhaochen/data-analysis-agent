-- ============================================================
-- 场景：月度整体下单转化率对比（支付订单数 / 访客数，不分品类）
-- 适用：转化率环比/同比、促销期/自然期同口径验证、大促月剔除结构效应
-- 参数：替换日期范围（orders 按 order_dt、traffic 按 dt，左闭右开；
--   写法一需同步改 CASE 两分支与 WHERE；写法二需改 traffic/orders 范围与月份 CASE）
-- 关联键：无跨表 1:N 关联（整体口径不分品类，orders 与 traffic 仅按日对齐）
-- 粒度对齐：分子 = COUNT(DISTINCT order_id)；分母 = SUM(traffic.uv) 人次口径
--   （跨天访客重复，周期对比口径一致即可，勿宣称独立访客数）
-- 注意事项：
--   1. 整体转化率不要用品类版片段（category_conversion_rate.sql，分子按品类归属）
--   2. 支付订单 = pay_dt IS NOT NULL（cancelled 天然无 pay_dt，含 refunded）
--   3. 促销/自然期拆分只能按「天」划分（流量无订单级促销归属）：
--      促销期日 = 当天被任一活动覆盖（promo_calendar 区间含首尾，见 traffic.md）
--   4. 大促月对比先查促销日历（如 618）：整月环比会被大促结构效应误导，
--      必要时补写法二做同口径矩阵；结果用 days 列自检天数加总
-- ============================================================

-- 写法一：整月转化率环比（2026-06 vs 2026-07，两月为一组）
WITH paid AS (
    SELECT CASE WHEN order_dt >= '2026-06-01' AND order_dt < '2026-07-01' THEN '2026-06'
                ELSE '2026-07' END AS mon,
           COUNT(DISTINCT order_id) AS paid_cnt
    FROM orders
    WHERE pay_dt IS NOT NULL
      AND ((order_dt >= '2026-06-01' AND order_dt < '2026-07-01')
        OR (order_dt >= '2026-07-01' AND order_dt < '2026-08-01'))
    GROUP BY mon
),
visits AS (
    SELECT CASE WHEN dt >= '2026-06-01' AND dt < '2026-07-01' THEN '2026-06'
                ELSE '2026-07' END AS mon,
           SUM(uv) AS uv
    FROM traffic
    WHERE (dt >= '2026-06-01' AND dt < '2026-07-01')
       OR (dt >= '2026-07-01' AND dt < '2026-08-01')
    GROUP BY mon
)
SELECT p.mon AS month, p.paid_cnt AS paid_orders, v.uv AS visitors,
       ROUND(p.paid_cnt * 100.0 / v.uv, 2) AS conv_rate_pct
FROM paid p
JOIN visits v ON p.mon = v.mon
ORDER BY p.mon;

-- 写法二：促销期/自然期 × 月 转化率矩阵（按天划分，2026-06 ~ 2026-07）
WITH daily AS (
    SELECT t.dt,
           CASE WHEN EXISTS (SELECT 1 FROM promo_calendar pc
                             WHERE pc.start_dt <= t.dt AND pc.end_dt >= t.dt)
                THEN '促销期' ELSE '自然期' END AS period,
           SUM(t.uv) AS uv
    FROM traffic t
    WHERE t.dt >= '2026-06-01' AND t.dt < '2026-08-01'
    GROUP BY t.dt, period
),
paid_daily AS (
    SELECT order_dt, COUNT(DISTINCT order_id) AS paid_cnt
    FROM orders
    WHERE pay_dt IS NOT NULL
      AND order_dt >= '2026-06-01' AND order_dt < '2026-08-01'
    GROUP BY order_dt
)
SELECT CASE WHEN d.dt < '2026-07-01' THEN '2026-06' ELSE '2026-07' END AS month,
       d.period, COUNT(*) AS days, SUM(d.uv) AS visitors,
       COALESCE(SUM(p.paid_cnt), 0) AS paid_orders,
       ROUND(COALESCE(SUM(p.paid_cnt), 0) * 100.0 / SUM(d.uv), 2) AS conv_rate_pct
FROM daily d
LEFT JOIN paid_daily p ON p.order_dt = d.dt
GROUP BY month, d.period
ORDER BY month, d.period;
