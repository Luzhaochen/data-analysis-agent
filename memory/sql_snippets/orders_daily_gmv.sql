-- ============================================================
-- 场景：每日 GMV 趋势（含自然期/促销期拆分）
-- 适用：日粒度 GMV / 订单量 / 客单价趋势分析
-- 参数：替换 WHERE 中的日期范围（左闭右开，见 sql_syntax.md §1）
-- 关联键：无（单表）
-- 粒度：orders 一行一单，直接聚合无需去重
-- 注意事项：
--   1. 金额口径过滤 cancelled（cancelled 的 pay_amt=0）
--   2. promo_id IS NULL = 自然期；IS NOT NULL = 促销期
--   3. 要渠道拆分时另加 channel 列，并限定 order_dt >= '2025-06-01'
-- ============================================================
SELECT order_dt,
       COUNT(*)                                                  AS order_cnt,
       ROUND(SUM(pay_amt), 2)                                    AS gmv,
       ROUND(SUM(CASE WHEN promo_id IS NULL THEN pay_amt ELSE 0 END), 2)      AS natural_gmv,
       ROUND(SUM(CASE WHEN promo_id IS NOT NULL THEN pay_amt ELSE 0 END), 2)  AS promo_gmv,
       ROUND(SUM(pay_amt) / COUNT(*), 2)                         AS avg_order_value
FROM orders
WHERE order_status <> 'cancelled'
  AND order_dt >= '2026-06-01' AND order_dt < '2026-07-01'
GROUP BY order_dt
ORDER BY order_dt;
