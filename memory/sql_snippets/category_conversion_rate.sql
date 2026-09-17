-- ============================================================
-- 场景：各二级品类下单转化率（支付订单数 / 访客数）
-- 适用：转化率排行、品类流量效率对比、漏斗健康度分析
-- 参数：替换两处日期范围（orders 按下单日、traffic 按 dt，左闭右开）
-- 关联键：orders → order_items(order_id) → products(product_id 拿二级品类)；
--   traffic.category_id → categories.category_id
-- 粒度对齐：分子按明细归属二级品类（跨品类订单重复计分子，品类间不可求和）；
--   分母 = SUM(traffic.uv) 人次口径（跨天访客重复，见 traffic.md 坑 1）
-- 注意事项：
--   1. 支付订单 = pay_dt IS NOT NULL（cancelled 天然无 pay_dt）
--   2. 时间口径：订单按下单日 order_dt、流量按 dt，两个范围必须一致
--   3. 整体转化率（不分品类）不要用本片段——直接 COUNT(DISTINCT order_id) / SUM(uv)
-- ============================================================
WITH paid_orders AS (
    SELECT p.category_id, COUNT(DISTINCT oi.order_id) AS paid_cnt
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.order_id
    JOIN products p ON oi.product_id = p.product_id
    WHERE o.pay_dt IS NOT NULL
      AND o.order_dt >= '2026-07-01' AND o.order_dt < '2026-08-01'
    GROUP BY p.category_id
),
visits AS (
    SELECT category_id, SUM(uv) AS uv
    FROM traffic
    WHERE dt >= '2026-07-01' AND dt < '2026-08-01'
    GROUP BY category_id
)
SELECT c.category_name,
       COALESCE(po.paid_cnt, 0)                       AS paid_orders,
       v.uv,
       ROUND(COALESCE(po.paid_cnt, 0) / v.uv * 100, 2) AS conv_rate_pct
FROM visits v
LEFT JOIN paid_orders po ON v.category_id = po.category_id
JOIN categories c ON v.category_id = c.category_id
ORDER BY conv_rate_pct DESC;
