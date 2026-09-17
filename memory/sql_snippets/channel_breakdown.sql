-- ============================================================
-- 场景：各下单渠道的订单量与实付金额对比
-- 适用：渠道结构分析、渠道客单价对比
-- 参数：替换 WHERE 中的日期范围（左闭右开，见 sql_syntax.md §1）
-- 关联键：无（单表）
-- 粒度：orders 一行一单，直接聚合无需去重
-- 注意事项：
--   1. 金额口径 = 团队默认 GMV 口径（<> cancelled，含退款）；若需严格完成口径改 = 'completed'
--   2. channel 在 2025-06 前为 NULL → 分析历史区间时必须 COALESCE 归「未知渠道」，
--      2025-06 起无 NULL（本片段已含归类，两类区间均安全）
--   3. 客单价 = total_pay_amt / order_cnt（口径与金额一致）
-- ============================================================
SELECT COALESCE(channel, '未知渠道')        AS channel,
       COUNT(*)                            AS order_cnt,
       ROUND(SUM(pay_amt), 2)              AS total_pay_amt,
       ROUND(SUM(pay_amt) / COUNT(*), 2)   AS avg_order_value
FROM orders
WHERE order_status <> 'cancelled'
  AND order_dt >= '2026-01-01' AND order_dt < '2026-07-01'
GROUP BY COALESCE(channel, '未知渠道')
ORDER BY total_pay_amt DESC;
