-- ============================================================
-- 场景：一级品类上卷分析（订单 GMV / 有效订单量 / 促销订单占比）
-- 适用：品类维度下钻与上卷、促销渗透分析、品类结构对比
-- 参数：替换 WHERE 中的日期范围（左闭右开，见 sql_syntax.md §1）
-- 关联键：orders → order_items(order_id) → products(product_id) → categories(category_id)
--   上卷：COALESCE(parent_id, category_id)——二级品类用父级 ID，一级品类用自身
-- 粒度对齐：GMV 按明细行归属品类（拆分口径）；跨品类订单在品类订单量中重复计数，
--   品类间订单量不可求和（见 categories.md 坑 4）
-- 注意事项：
--   1. 金额口径 = 团队默认 GMV（order_status <> 'cancelled'）
--   2. 促销订单 = promo_id IS NOT NULL；自然期订单占比 = 100 - promo_order_pct
--   3. 时间过滤在 orders.order_dt（按下单日归属）
-- ============================================================
WITH cat_map AS (
    SELECT category_id, COALESCE(parent_id, category_id) AS lvl1_id
    FROM categories
),
base AS (
    SELECT cm.lvl1_id, o.order_id, o.promo_id, SUM(oi.gmv) AS order_gmv
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.order_id
    JOIN products p ON oi.product_id = p.product_id
    JOIN cat_map cm ON p.category_id = cm.category_id
    WHERE o.order_status <> 'cancelled'
      AND o.order_dt >= '2026-04-01' AND o.order_dt < '2026-07-01'
    GROUP BY cm.lvl1_id, o.order_id, o.promo_id
)
SELECT c.category_name,
       ROUND(SUM(b.order_gmv), 2)                                        AS order_gmv,
       COUNT(DISTINCT b.order_id)                                        AS valid_orders,
       ROUND(COUNT(DISTINCT CASE WHEN b.promo_id IS NOT NULL THEN b.order_id END)
             / COUNT(DISTINCT b.order_id) * 100, 2)                      AS promo_order_pct
FROM base b
JOIN categories c ON b.lvl1_id = c.category_id
GROUP BY b.lvl1_id, c.category_name
ORDER BY order_gmv DESC;
