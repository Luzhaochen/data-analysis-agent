-- ============================================================
-- 场景：各退款原因的退款金额与笔数分布
-- 适用：退款构成分析、退款原因对比、退款率分子
-- 参数：替换 WHERE 中的日期范围（左闭右开，见 sql_syntax.md §1）
-- 关联键：无（单表）
-- 粒度：refunds 一行一退款单，直接聚合无需去重
-- 注意事项：
--   1. 时间归属 = 退款发生日 refund_dt；若需按原订单下单日归属，JOIN orders 用 order_dt
--   2. 全表含 3 条脏数据（refund_id 1/2/3，refund_dt='2024-12-31' 早于下单日，
--      共 35,337.11 元）——查询区间含 2024-12-31 时先剔除；2025-01-01 起不受影响
--   3. 一个订单可有多笔退款，笔数用 COUNT(*)，勿用 COUNT(DISTINCT order_id)
--   4. refund_reason 全表仅 5 种取值（价格保护/物流破损/不想要了/七天无理由/质量问题），无 NULL
-- ============================================================
SELECT refund_reason                AS refund_reason,
       COUNT(*)                    AS refund_cnt,
       ROUND(SUM(refund_amt), 2)   AS total_refund_amt
FROM refunds
WHERE refund_dt >= '2026-01-01' AND refund_dt < '2026-07-01'
GROUP BY refund_reason
ORDER BY total_refund_amt DESC;
