# 核查任务（参与者材料 ①）

你是团队的数据同事。下面是分析助手产生的两份输出。请像平时核查口径一样，**标记你认为有错误的口径说明（打 ✗），并写一句原因**。**不必懂业务**——对照随附的《知识库摘录》检查说法是否一致即可。

---

## 任务 A：2026 年 Q2 GMV 分析

**问题**：2026 年 Q2 的总实付金额、有效订单量与平均客单价。

**SQL**：

```sql
SELECT COUNT(*)                        AS valid_orders,
       ROUND(SUM(pay_amt), 2)          AS gmv,
       ROUND(SUM(pay_amt)/COUNT(*), 2) AS avg_price
FROM orders
WHERE order_dt >= '2026-04-01' AND order_dt < '2026-07-01'
  AND order_status <> 'cancelled';
```

**结果**：valid_orders = 42,161 · gmv = 313,192,219.05 · avg_price = 7,428.48

**口径说明**（逐条审查）：

**①** GMV = SUM(pay_amt)，排除 order_status = 'cancelled'
　　[来源：memory/tables/orders.md「指标口径」]
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

**②** 时间归属按创建时间 created_dt，范围 2026-04-01 ~ 2026-07-01
　　[来源：memory/tables/orders.md「时间字段」]
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

**③** 有效订单 = 除 cancelled 外的全部订单
　　[来源：memory/tables/orders.md「指标口径」]
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

**④** 客单价 = 总实付金额 ÷ 商品明细行数
　　[来源：memory/tables/orders.md「指标口径」]
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

---

## 任务 B：2026 年 Q1 退款率

**问题**：2026 年 Q1 的退款率。

**SQL**：

```sql
SELECT ROUND(SUM(r.refund_amt) / g.gmv * 100, 4) AS refund_rate_pct
FROM refunds r
CROSS JOIN (
    SELECT SUM(pay_amt) AS gmv
    FROM orders
    WHERE order_dt >= '2026-01-01' AND order_dt < '2026-04-01'
      AND order_status <> 'cancelled'
) g
WHERE r.refund_dt >= '2026-01-01' AND r.refund_dt < '2026-04-01';
```

**结果**：refund_rate_pct = 2.3335

**口径说明**（逐条审查）：

**①** 退款金额按退款日 refund_dt 归属
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

**②** 统计前已剔除 refund_id ∈ {1, 2, 3} 三条脏数据
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

**③** 分母 GMV 排除 cancelled
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

**④** 退款率 = 退款笔数 ÷ 有效订单数（1,179 ÷ 36,295 ≈ 3.25%）
　　□ 正确　□ 有错（原因：＿＿＿＿＿＿＿＿＿＿＿＿＿＿）

---

*答完后：哪一条你觉得最可疑？当时你查了摘录的哪部分？*
