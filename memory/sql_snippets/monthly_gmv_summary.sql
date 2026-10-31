-- ============================================================
-- 场景：月度 GMV 汇总（含自然期/促销期拆分、订单量与客单价）
-- 适用：GMV 月度环比 / 促销结构对比 / 增量拆解的数据底表
-- 参数：每个 UNION ALL 分段改一个月份区间（左闭右开，见 sql_syntax.md §1）；
--   要 N 个月就写 N 个分段，段内 WHERE 完整重复
-- 关联键：无（单表）
-- 粒度：orders 一行一单，按月份分段聚合，无需去重
-- 注意事项：
--   1. 金额口径过滤 cancelled（cancelled 的 pay_amt=0）
--   2. 【性能】禁止 GROUP BY CASE/年月函数按月聚合：实测优化器放弃
--      idx_order_dt，全表扫描 28.5 万行 + Using temporary + filesort；
--      分段 UNION ALL 后每段走范围扫描（18538 / 23576 行），末尾临时表仅 N 行。
--      证据：EXPLAIN dry-run 记录在 runs/20260930-gmv-2m/retry_log.json
--      （会话 20260930-gmv-2m）；本库其余按月聚合片段（如
--      monthly_conv_rate_comparison.sql 写法一）遇大范围同样建议改分段写法
--   3. 金额精确计算留在 SQL 内（ROUND 后输出），不做客户端加总
-- ============================================================
SELECT '2026-07' AS ym,
       COUNT(*)                                                          AS order_cnt,
       ROUND(SUM(pay_amt), 2)                                            AS gmv,
       ROUND(SUM(CASE WHEN promo_id IS NULL THEN pay_amt ELSE 0 END), 2)     AS natural_gmv,
       ROUND(SUM(CASE WHEN promo_id IS NOT NULL THEN pay_amt ELSE 0 END), 2) AS promo_gmv,
       ROUND(SUM(pay_amt) / COUNT(*), 2)                                 AS avg_order_value
FROM orders
WHERE order_status <> 'cancelled'
  AND order_dt >= '2026-07-01' AND order_dt < '2026-08-01'
UNION ALL
SELECT '2026-08' AS ym,
       COUNT(*)                                                          AS order_cnt,
       ROUND(SUM(pay_amt), 2)                                            AS gmv,
       ROUND(SUM(CASE WHEN promo_id IS NULL THEN pay_amt ELSE 0 END), 2)     AS natural_gmv,
       ROUND(SUM(CASE WHEN promo_id IS NOT NULL THEN pay_amt ELSE 0 END), 2) AS promo_gmv,
       ROUND(SUM(pay_amt) / COUNT(*), 2)                                 AS avg_order_value
FROM orders
WHERE order_status <> 'cancelled'
  AND order_dt >= '2026-08-01' AND order_dt < '2026-09-01'
ORDER BY 1;
