# -*- coding: utf-8 -*-
"""check_data.py · 数据体检：验证入库数据与生成器"已知答案"一致

用只读账号 data_agent 连接（密码从 setup.sql 读取），不会改动数据。

用法：
  .venv\\Scripts\\python mock_data\\check_data.py
"""
import re
import sys

import pymysql


def main():
    # 只读账号密码从 setup.sql 解析，不进对话、不进命令行
    sql = open(__file__.replace("check_data.py", "setup.sql"), encoding="utf-8").read()
    pw = re.search(r"IDENTIFIED BY '([^']+)'", sql).group(1)
    conn = pymysql.connect(host="127.0.0.1", port=3306, user="data_agent",
                           password=pw, database="jd_demo", charset="utf8mb4")
    cur = conn.cursor()

    def q(sql):
        cur.execute(sql)
        return cur.fetchall()

    print("=" * 66)
    print("数据体检（对照生成器『已知答案』）")
    print("=" * 66)

    # 1. 行数
    print("\n[行数]")
    for t in ["categories", "products", "users", "promo_calendar",
              "orders", "order_items", "traffic", "refunds"]:
        print(f"  {t:<16} {q(f'SELECT COUNT(*) FROM {t}')[0][0]:>10,}")
    print("  orders 日期范围:", q("SELECT MIN(order_dt), MAX(order_dt) FROM orders")[0])
    print("  promo_calendar 列:",
          [r[0] for r in q("SHOW COLUMNS FROM promo_calendar")])

    # 2. NULL 分布（解释 channel/promo_id 为 NULL 的设计）
    print("\n[NULL 分布]")
    print("  channel 为 NULL 占比:",
          f"{q('SELECT SUM(channel IS NULL)/COUNT(*) FROM orders')[0][0]*100:.1f}%")
    print("  promo_id 为 NULL 占比:",
          f"{q('SELECT SUM(promo_id IS NULL)/COUNT(*) FROM orders')[0][0]*100:.1f}%")
    print("  促销活动总数:", q("SELECT COUNT(*) FROM promo_calendar")[0][0],
          " / 订单中出现的 distinct promo_id:",
          q("SELECT COUNT(DISTINCT promo_id) FROM orders")[0][0])
    print("\n  按月分布（channel 空 / promo 空 / 总数）:")
    for ym, chan_null, promo_null, n in q(
            "SELECT DATE_FORMAT(order_dt,'%Y-%m'), SUM(channel IS NULL), "
            "SUM(promo_id IS NULL), COUNT(*) FROM orders "
            "GROUP BY DATE_FORMAT(order_dt,'%Y-%m') "
            "ORDER BY DATE_FORMAT(order_dt,'%Y-%m')"):
        print(f"  {ym}  n={n:>6,}  channel空 {chan_null:>6,}  promo空 {promo_null:>6,}")

    # 3. 边界样例
    print("\n[边界样例]")
    print("  最早 3 笔（应 channel/promo_id 全 NULL）:")
    for r in q("SELECT order_id, order_dt, order_status, channel, promo_id, pay_amt "
               "FROM orders ORDER BY order_id LIMIT 3"):
        print("   ", r)
    print("  2025-06-01 起最早 3 笔（channel 应有值）:")
    for r in q("SELECT order_id, order_dt, channel, promo_id "
               "FROM orders WHERE order_dt >= '2025-06-01' ORDER BY order_id LIMIT 3"):
        print("   ", r)
    print("  促销订单样例 3 笔:")
    for r in q("SELECT order_id, order_dt, promo_id, pay_amt "
               "FROM orders WHERE promo_id IS NOT NULL ORDER BY order_id LIMIT 3"):
        print("   ", r)

    # 4. 各表抽查
    print("\n[各表抽查]")
    print("  categories 层级分布:",
          q("SELECT category_level, COUNT(*) FROM categories GROUP BY category_level"))
    print("  products 品类数/品牌数:",
          q("SELECT COUNT(DISTINCT category_id), COUNT(DISTINCT brand) FROM products")[0])
    print("  users 城市数:", q("SELECT COUNT(DISTINCT city) FROM users")[0][0],
          " vip分布:", q("SELECT vip_level, COUNT(*) FROM users GROUP BY vip_level"))
    print("  promo_calendar 等级分布:",
          q("SELECT level, COUNT(*) FROM promo_calendar GROUP BY level"),
          " duration_days 空值:",
          q("SELECT SUM(duration_days IS NULL) FROM promo_calendar")[0][0])
    print("  orders 状态分布:",
          q("SELECT order_status, COUNT(*) FROM orders GROUP BY order_status"))
    print("  cancelled 异常(有pay_amt/有pay_dt):",
          q("SELECT SUM(pay_amt <> 0), SUM(pay_dt IS NOT NULL) "
            "FROM orders WHERE order_status='cancelled'")[0])
    print("  traffic 覆盖天数:", q("SELECT COUNT(DISTINCT dt) FROM traffic")[0][0],
          "(预期 608)")
    print("  refunds 原因分布:",
          q("SELECT refund_reason, COUNT(*) FROM refunds GROUP BY refund_reason"))
    print("  orders 孤儿 user_id:", q(
        "SELECT COUNT(*) FROM orders o LEFT JOIN users u USING(user_id) "
        "WHERE u.user_id IS NULL")[0][0])
    print("  order_items 孤儿 product_id:", q(
        "SELECT COUNT(*) FROM order_items oi LEFT JOIN products p USING(product_id) "
        "WHERE p.product_id IS NULL")[0][0])
    print("  orders 孤儿 promo_id(非NULL):", q(
        "SELECT COUNT(*) FROM orders o LEFT JOIN promo_calendar p USING(promo_id) "
        "WHERE o.promo_id IS NOT NULL AND p.promo_id IS NULL")[0][0])
    print("  item_cnt 与明细行数不一致的订单:", q(
        "SELECT COUNT(*) FROM orders o WHERE o.item_cnt <> "
        "(SELECT COUNT(*) FROM order_items oi WHERE oi.order_id = o.order_id)")[0][0])
    print("  pay_amt 与明细gmv不一致的完成单:", q(
        "SELECT COUNT(*) FROM orders o WHERE o.order_status <> 'cancelled' "
        "AND ABS(o.pay_amt - (SELECT COALESCE(SUM(oi.gmv),0) "
        "FROM order_items oi WHERE oi.order_id = o.order_id)) > 0.01")[0][0],
        "(预期 2 = price 漂移脏数据)")

    # 5. 已知答案核对
    print("\n[已知答案核对]")
    h1 = q(
        "SELECT SUM(CASE WHEN order_dt BETWEEN '2025-01-01' AND '2025-06-30' "
        "THEN pay_amt ELSE 0 END)/10000, "
        "SUM(CASE WHEN order_dt BETWEEN '2026-01-01' AND '2026-06-30' "
        "THEN pay_amt ELSE 0 END)/10000 "
        "FROM orders WHERE order_status <> 'cancelled'")[0]
    print(f"  2025H1 总GMV {float(h1[0]):10.2f}万 / 2026H1 总GMV {float(h1[1]):10.2f}万")
    diff = q(
        "SELECT (SELECT SUM(oi.gmv) FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        "WHERE o.order_status <> 'cancelled') "
        "- (SELECT SUM(pay_amt) FROM orders "
        "WHERE order_status <> 'cancelled')")[0][0]
    print(f"  对账差额 = {float(diff):.2f} 元（与生成器输出的 price_漂移预期差额 对照）")
    bad_refund = q(
        "SELECT COUNT(*) FROM refunds r JOIN orders o USING(order_id) "
        "WHERE r.refund_dt < o.order_dt")[0][0]
    print(f"  退款时间矛盾 = {bad_refund} 条（生成器预期 3）")

    conn.close()


if __name__ == "__main__":
    main()
