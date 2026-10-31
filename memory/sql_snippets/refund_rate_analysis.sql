-- ============================================================
-- 场景：退款率（金额口径）整体 / 按月 / 分维度（退款原因、促销等级、一级品类）
-- 适用：季度/月度退款率、退款构成、促销与自然期退款对比、品类退款对比
-- 参数：替换所有日期范围（refunds 按 refund_dt、orders 按 order_dt，左闭右开；
--   写法二需同步改 CASE 三分支与 WHERE）
-- 关联键：refunds.order_id → orders.order_id（N:1）；orders.promo_id → promo_calendar.promo_id（N:1，NULL=自然期）；
--   order_items.order_id → orders.order_id（N:1）；products.category_id → categories（二级行）→ parent_id 上卷一级
-- 粒度：整体/月/原因/促销等级写法中 refunds→orders 为 N:1 不膨胀；品类写法按 SKU 成交额占比分摊退款（拆分口径）
-- 注意事项：
--   1. 口径（2026-10-31 会话确认）：金额口径 = 退款金额 ÷ 同期 GMV，默认按退款发生日 refund_dt 归属；
--      下单日归属需 JOIN orders 用 order_dt，两种口径结果不同，用前与用户确认（见 refunds.md「指标口径」）
--   2. 分母 GMV：orders.pay_amt，order_status <> 'cancelled'，按 order_dt 归属，全部订单（不限促销）
--   3. 脏数据：refund_id 1/2/3（refund_dt='2024-12-31'）仅在查询区间含 2024-12-31 时需剔除
--   4. 数据边界：refund_dt 比 orders 覆盖范围两端各多几天 → 跨表比较注意区间天然对不齐（refunds.md「坑」）
--   5. 品类分摊：订单级退款按订单内各 SKU 成交额（order_items.gmv）占比分摊（2026-10-31 会话确认），
--      一级品类必须经 categories.parent_id 且 c1.category_level = 1（categories.md「坑」2）
--   6. 执行后对账（五查）：各维度退款合计应等于整体 SUM(refund_amt)；品类分摊合计无损则孤儿退款单为 0
--      （写法六探针）；order_items 口径 GMV 与 orders.pay_amt 有 2 条脏数据差额 694,302.84（orders.md「坑」3），
--      差额出现时先定位脏数据再解读
-- ============================================================

-- 写法一：整体单值（示例 2026 Q1）
SELECT r.q1_refund_amt, o.q1_gmv, ROUND(r.q1_refund_amt / o.q1_gmv, 6) AS refund_rate
FROM (SELECT ROUND(SUM(refund_amt), 2) AS q1_refund_amt
      FROM refunds
      WHERE refund_dt >= '2026-01-01' AND refund_dt < '2026-04-01') r
CROSS JOIN (SELECT ROUND(SUM(pay_amt), 2) AS q1_gmv
            FROM orders
            WHERE order_dt >= '2026-01-01' AND order_dt < '2026-04-01'
              AND order_status <> 'cancelled') o;

-- 写法二：按月趋势（CASE 分桶，勿在时间字段上套 DATE_FORMAT）
SELECT r.mon AS month, r.refund_amt, o.gmv, ROUND(r.refund_amt / o.gmv, 6) AS refund_rate
FROM (SELECT CASE WHEN refund_dt < '2026-02-01' THEN '2026-01'
                  WHEN refund_dt < '2026-03-01' THEN '2026-02'
                  ELSE '2026-03' END AS mon,
             ROUND(SUM(refund_amt), 2) AS refund_amt
      FROM refunds
      WHERE refund_dt >= '2026-01-01' AND refund_dt < '2026-04-01'
      GROUP BY mon) r
JOIN (SELECT CASE WHEN order_dt < '2026-02-01' THEN '2026-01'
                  WHEN order_dt < '2026-03-01' THEN '2026-02'
                  ELSE '2026-03' END AS mon,
             ROUND(SUM(pay_amt), 2) AS gmv
      FROM orders
      WHERE order_dt >= '2026-01-01' AND order_dt < '2026-04-01'
        AND order_status <> 'cancelled'
      GROUP BY mon) o ON r.mon = o.mon
ORDER BY r.mon;

-- 写法三：退款原因下钻（各原因率之和 = 整体退款率）
SELECT r.refund_reason, ROUND(r.refund_amt, 2) AS refund_amt,
       ROUND(r.refund_amt / o.q1_gmv, 6) AS refund_rate
FROM (SELECT refund_reason, SUM(refund_amt) AS refund_amt
      FROM refunds
      WHERE refund_dt >= '2026-01-01' AND refund_dt < '2026-04-01'
      GROUP BY refund_reason) r
CROSS JOIN (SELECT SUM(pay_amt) AS q1_gmv
            FROM orders
            WHERE order_dt >= '2026-01-01' AND order_dt < '2026-04-01'
              AND order_status <> 'cancelled') o
ORDER BY r.refund_amt DESC;

-- 写法四：促销等级下钻（NULL=自然期，LEFT JOIN 保留；分母侧为准，无退款等级记 0）
SELECT g.promo_level, ROUND(COALESCE(r.refund_amt, 0), 2) AS refund_amt,
       ROUND(g.gmv, 2) AS gmv,
       ROUND(COALESCE(r.refund_amt, 0) / g.gmv, 6) AS refund_rate
FROM (SELECT COALESCE(pc.level, '自然期') AS promo_level, SUM(o.pay_amt) AS gmv
      FROM orders o
      LEFT JOIN promo_calendar pc ON pc.promo_id = o.promo_id
      WHERE o.order_dt >= '2026-01-01' AND o.order_dt < '2026-04-01'
        AND o.order_status <> 'cancelled'
      GROUP BY COALESCE(pc.level, '自然期')) g
LEFT JOIN (SELECT COALESCE(pc.level, '自然期') AS promo_level, SUM(rf.refund_amt) AS refund_amt
           FROM refunds rf
           JOIN orders o ON o.order_id = rf.order_id
           LEFT JOIN promo_calendar pc ON pc.promo_id = o.promo_id
           WHERE rf.refund_dt >= '2026-01-01' AND rf.refund_dt < '2026-04-01'
           GROUP BY COALESCE(pc.level, '自然期')) r ON r.promo_level = g.promo_level
ORDER BY g.gmv DESC;

-- 写法五：一级品类下钻（订单级退款按 SKU 成交额占比分摊 → parent_id 上卷；num/den 取并集防漏）
WITH q1_refunds AS (
    SELECT order_id, SUM(refund_amt) AS refund_amt
    FROM refunds
    WHERE refund_dt >= '2026-01-01' AND refund_dt < '2026-04-01'
    GROUP BY order_id
),
ord_items AS (
    SELECT oi.order_id, oi.product_id,
           SUM(oi.gmv) AS item_gmv,
           SUM(SUM(oi.gmv)) OVER (PARTITION BY oi.order_id) AS ord_gmv
    FROM order_items oi
    WHERE oi.order_id IN (SELECT order_id FROM q1_refunds)
    GROUP BY oi.order_id, oi.product_id
),
num AS (
    SELECT c1.category_id, c1.category_name AS category_lvl1,
           SUM(q.refund_amt * oi.item_gmv / oi.ord_gmv) AS refund_amt_attributed
    FROM q1_refunds q
    JOIN ord_items oi ON oi.order_id = q.order_id
    JOIN products p ON p.product_id = oi.product_id
    JOIN categories c2 ON c2.category_id = p.category_id
    JOIN categories c1 ON c1.category_id = c2.parent_id AND c1.category_level = 1
    GROUP BY c1.category_id, c1.category_name
),
den AS (
    SELECT c1.category_id, c1.category_name AS category_lvl1, SUM(oi.gmv) AS gmv
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN products p ON p.product_id = oi.product_id
    JOIN categories c2 ON c2.category_id = p.category_id
    JOIN categories c1 ON c1.category_id = c2.parent_id AND c1.category_level = 1
    WHERE o.order_dt >= '2026-01-01' AND o.order_dt < '2026-04-01'
      AND o.order_status <> 'cancelled'
    GROUP BY c1.category_id, c1.category_name
),
levels AS (
    SELECT category_id, category_lvl1 FROM num
    UNION SELECT category_id, category_lvl1 FROM den
)
SELECT l.category_lvl1,
       ROUND(COALESCE(n.refund_amt_attributed, 0), 2) AS refund_amt_attributed,
       ROUND(COALESCE(d.gmv, 0), 2) AS gmv,
       ROUND(COALESCE(n.refund_amt_attributed, 0) / NULLIF(d.gmv, 0), 6) AS refund_rate
FROM levels l
LEFT JOIN num n ON n.category_id = l.category_id
LEFT JOIN den d ON d.category_id = l.category_id
ORDER BY gmv DESC;

-- 写法六：对账探针（执行跨表下钻前先探孤儿，两个都应为 0）
-- 孤儿退款单（refund 无对应 orders 行）
SELECT COUNT(*) AS orphan_refunds
FROM refunds rf
LEFT JOIN orders o ON o.order_id = rf.order_id
WHERE rf.refund_dt >= '2026-01-01' AND rf.refund_dt < '2026-04-01'
  AND o.order_id IS NULL;

-- 无明细退款订单（refund 所在订单无 order_items 行 → 品类分摊会丢金额）
SELECT COUNT(DISTINCT rf.order_id) AS refund_orders_without_items
FROM refunds rf
LEFT JOIN order_items oi ON oi.order_id = rf.order_id
WHERE rf.refund_dt >= '2026-01-01' AND rf.refund_dt < '2026-04-01'
  AND oi.item_id IS NULL;
