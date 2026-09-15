-- ============================================================
-- 场景：促销活动效果对比（活动 GMV / 订单量 / 日均 GMV）
-- 适用：对比不同等级/类型活动的效果，识别「高频低效」活动
-- 参数：替换 WHERE 中 p.start_dt 范围与 p.level（如 'S'/'A'/'B'）
-- 关联键：orders.promo_id → promo_calendar.promo_id（N:1，NULL 不参与）
-- 粒度对齐：promo_calendar 一行一活动；orders 先按 promo_id 聚合再 JOIN（先聚合再关联）
-- 注意事项：
--   1. 不同时长活动必须比日均（gmv / duration_days），不能比总量
--   2. 活动归属用 orders.promo_id 精确关联，禁止按 start_dt/end_dt 区间 JOIN（区间可能重叠）
--   3. GMV 过滤 cancelled
-- ============================================================
SELECT p.promo_id,
       p.promo_name,
       p.level,
       p.promo_type,
       p.duration_days,
       o.order_cnt,
       ROUND(o.gmv, 2)                   AS gmv,
       ROUND(o.gmv / p.duration_days, 2) AS daily_gmv
FROM promo_calendar p
JOIN (
    SELECT promo_id,
           COUNT(*)     AS order_cnt,
           SUM(pay_amt) AS gmv
    FROM orders
    WHERE order_status <> 'cancelled'
      AND promo_id IS NOT NULL
    GROUP BY promo_id
) o ON o.promo_id = p.promo_id
WHERE p.start_dt >= '2026-01-01'
ORDER BY p.level, daily_gmv DESC;
