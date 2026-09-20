# -*- coding: utf-8 -*-
"""gen_mock_data.py · 模拟数据生成器（京东大家电风格）

数据范围：2025-01-01 ~ 2026-08-31，8 张表，28.7 万订单 / 45.9 万明细。

业务模型（全部可控、可复现、有"已知答案"）：
  1. 基线：日均约 300 单，周末高（WEEKLY），每月 +2.5% 增长趋势
  2. 季节性：每个二级品类 12 个月的季节系数（空调夏高冬低、热水器冬高…）
  3. 促销效应（复刻你京东实习项目的现象）：
     - 活动期间促销订单增量（uplift）
     - 活动期间自然期订单被挤压（SQUEEZE=0.55）
     - 活动结束后自然期需 RECOVERY 天线性恢复（S:8 A:5 B:3）→"恢复期"
     - 促销疲劳：活动开始前 2 天自然需求被抑制（消费者等促销）
     - 2026 上半年 B 级活动高频轮动（促销密度 33.7% → 71.3%）但单场增量低（1.15），
       且全年需求疲软（DEMAND_2026=0.72，促销常态化透支自然需求）
       → 复刻"促销密度大幅提升、促销占比飙升、自然GMV下滑、总GMV持平"的挤压故事
  4. 转化率故事：活动结束后订单按恢复期回升，但流量衰减只有 3 天尾巴
     → 大促结束后转化率（订单/uv）阶段性回落
  5. 埋好的脏数据（供 Step 4.5 结果校验与口径教学）：
     a. 3 条退款记录 refund_dt 早于 order_dt（时间矛盾）
     b. 2 条明细 price 放大 100 倍（单位漂移 → 对账不平）
     c. ~0.2% 促销订单 order_dt 落在活动区间外（归属口径漂移）
     d. 1 个已退单没有对应退款记录（关联丢行）
     e. channel 在 2025-06 之前为 NULL（历史字段缺失，正常业务现象）
  6. 对账教学点：orders.pay_amt 应等于明细 gmv 汇总（除 2 条脏数据外应一致）
  7. promo_calendar 对齐真实活动日历形态：activity_theme / duration_days
     （真实导出中 duration_days 可能是字符串如'1小时'——知识库"数据接入"章节讲）

用法：
  .venv\\Scripts\\python mock_data\\gen_mock_data.py            # 生成并入库（提示输入 root 密码）
  .venv\\Scripts\\python mock_data\\gen_mock_data.py --dry-run  # 只生成+打印统计，不连库
  .venv\\Scripts\\python mock_data\\gen_mock_data.py --seed 7   # 换随机种子

生成结束打印的统计摘要就是这批数据的"已知答案"，
后面用它检验 agent 的分析结论是否正确。
"""
from __future__ import annotations

import argparse
import getpass
import math
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

D = Decimal

# ---------------------------------------------------------------- 1. 常量
START, END = date(2025, 1, 1), date(2026, 8, 31)
SEED = 42

BASE_DAILY_ORDERS = 300.0          # 全平台日均订单基数
WEEKLY = [0.90, 0.95, 1.00, 1.00, 1.10, 1.25, 1.20]   # 周一..周日
MONTHLY_TREND = 0.025              # 每月 +2.5%
SQUEEZE = 0.55                     # 活动期间自然期订单挤压系数
RECOVERY_DAYS = {"S": 8, "A": 5, "B": 3}   # 活动结束后的自然期恢复天数
FATIGUE = 0.7                      # 促销疲劳：活动开始前 2 天内自然需求被抑制
DEMAND_2026 = 0.68                 # 2026 需求疲软：促销常态化透支自然需求
PROMO_MULT = {"S": 2.2, "A": 1.5, "B": 1.5}          # 2025 手写活动默认增量
B_UPLIFT_2026 = 1.15               # 2026 程序化 B 级活动增量（低效！）

CHANNELS = [("app", 0.60), ("pc", 0.20), ("miniprogram", 0.20)]
CHANNEL_NULL_BEFORE = date(2025, 6, 1)   # 该日期前 channel 无采集 → NULL

CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京",
          "西安", "重庆", "苏州", "天津", "郑州", "长沙", "青岛", "合肥",
          "沈阳", "济南", "福州", "昆明"]

# 品类结构：一级 -> 二级
CATEGORIES = [
    (101, "空调", 1), (102, "冰箱", 1), (103, "洗衣机", 1),
    (104, "平板电视", 1), (105, "热水器", 1),
    (106, "电饭煲", 2), (107, "净化器", 2), (108, "吸尘器", 2),
    (109, "手机", 3), (110, "耳机", 3),
]
LEVEL1 = [(1, "大家电"), (2, "小家电"), (3, "手机数码")]

# 自然订单的品类基础权重（未考虑季节性前）
CAT_BASE_WEIGHT = {"空调": 0.20, "冰箱": 0.15, "洗衣机": 0.13, "平板电视": 0.12,
                   "热水器": 0.10, "手机": 0.12, "耳机": 0.05, "电饭煲": 0.05,
                   "净化器": 0.04, "吸尘器": 0.04}

# 季节系数：index = 月份-1（1月..12月）
SEASONALITY = {
    "空调":     [0.50, 0.50, 0.70, 1.00, 1.60, 1.90, 2.00, 1.80, 1.20, 0.80, 0.60, 0.50],
    "冰箱":     [0.80, 0.80, 0.90, 1.00, 1.10, 1.30, 1.40, 1.30, 1.10, 1.00, 0.90, 0.85],
    "洗衣机":   [0.95, 0.95, 1.00, 1.05, 1.10, 1.10, 1.10, 1.05, 1.00, 1.00, 0.95, 0.95],
    "平板电视": [0.85, 0.90, 1.00, 1.05, 1.20, 1.15, 1.10, 1.10, 1.15, 1.20, 1.25, 1.10],
    "热水器":   [1.50, 1.40, 1.10, 0.90, 0.80, 0.70, 0.70, 0.80, 0.90, 1.20, 1.40, 1.60],
    "电饭煲":   [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 0.95, 0.95, 1.00, 1.05, 1.05, 1.05],
    "净化器":   [1.40, 1.20, 1.00, 0.85, 0.75, 0.70, 0.70, 0.80, 0.90, 1.10, 1.30, 1.50],
    "吸尘器":   [1.00, 1.00, 1.00, 1.00, 1.05, 1.05, 1.00, 1.00, 1.00, 1.05, 1.10, 1.10],
    "手机":     [0.95, 0.90, 1.00, 1.00, 1.05, 1.10, 1.05, 1.05, 1.30, 1.35, 1.25, 1.05],
    "耳机":     [0.95, 0.95, 1.00, 1.00, 1.05, 1.10, 1.05, 1.05, 1.20, 1.20, 1.25, 1.15],
}

# 每品类基础 UV（访客）
BASE_UV = {"空调": 25000, "冰箱": 18000, "洗衣机": 15000, "平板电视": 30000,
           "热水器": 12000, "电饭煲": 6000, "净化器": 5000, "吸尘器": 5000,
           "手机": 50000, "耳机": 20000}
TRAFFIC_MULT = {"S": 2.5, "A": 1.8, "B": 1.3}     # 活动期间 UV 放大
TRAFFIC_DECAY_DAYS = 4                            # 活动后 UV 衰减尾巴天数

# 商品目录：品类 -> [(品牌, 名称, 挂牌价)]
PRODUCTS_BY_CAT = {
    "空调":     [("格力", "云锦二代 1.5匹", 4599), ("美的", "酷省电 1.5匹", 2999),
                 ("海尔", "静悦 1.5匹", 3299), ("小米", "巨省电 1.5匹", 2499),
                 ("奥克斯", "京裕 1.5匹", 2199), ("海信", "舒适家 2匹", 5299)],
    "冰箱":     [("海尔", "星蕴 501L", 4999), ("美的", "慧鲜 465L", 3999),
                 ("容声", "离子净味 452L", 3499), ("西门子", "KA50 502L", 6899),
                 ("松下", "臻全嵌 453L", 7999)],
    "洗衣机":   [("海尔", "精华洗 10kg", 3999), ("小天鹅", "水魔方 10kg", 3599),
                 ("美的", "清风 10kg", 2599), ("LG", "星云 12kg", 5699)],
    "平板电视": [("小米", "S Pro 75", 6499), ("海信", "E8N 85", 9999),
                 ("TCL", "Q10K 65", 5599), ("索尼", "X90L 75", 12999),
                 ("创维", "A5D 55", 2999)],
    "热水器":   [("海尔", "超悦 60L", 1599), ("美的", "活水 60L", 1299),
                 ("万和", "燃气 16L", 1899), ("A.O.史密斯", "金圭 60L", 3999)],
    "电饭煲":   [("美的", "柴火饭 4L", 499), ("苏泊尔", "球釜 4L", 599),
                 ("九阳", "0涂层 3L", 399)],
    "净化器":   [("小米", "米家 4 Pro", 1099), ("飞利浦", "AC3737", 3299),
                 ("美的", "星澈 6L", 1999)],
    "吸尘器":   [("戴森", "V12 Slim", 3299), ("小狗", "T12 Plus", 1899),
                 ("美的", "P7 无线", 1099)],
    "手机":     [("华为", "Mate 70", 5999), ("小米", "15 Pro", 5299),
                 ("苹果", "iPhone 16", 6999), ("OPPO", "Find X8", 4999),
                 ("vivo", "X200", 4599)],
    "耳机":     [("苹果", "AirPods 4", 1299), ("索尼", "WF-1000XM5", 2199),
                 ("漫步者", "Lolli 3", 399), ("华为", "FreeBuds Pro 3", 1499)],
}

N_USERS = 60000


# ---------------------------------------------------------------- 2. 促销日历（手写 S/A + 程序化 2026 B）
def build_promos() -> list[dict]:
    """返回 [{name, level, type, target, start, end, uplift}]
    target=None 表示平台级（全品类）；否则为该二级品类名。
    uplift 为该活动促销订单相对当天基线的增量倍数。"""
    promos = [
        # ---- 2025 手写：密度低、B 级少但单场增量高 ----
        dict(name="2025年货节", level="S", type="平台大促", target=None,
             start=date(2025, 1, 18), end=date(2025, 1, 31)),
        dict(name="春季家装节", level="B", type="品类促销", target="冰箱",
             start=date(2025, 3, 1), end=date(2025, 3, 4)),
        dict(name="315品质家电周", level="A", type="平台大促", target=None,
             start=date(2025, 3, 10), end=date(2025, 3, 16)),
        dict(name="空调焕新节", level="B", type="品类促销", target="空调",
             start=date(2025, 4, 10), end=date(2025, 4, 13)),
        dict(name="五一焕新季", level="A", type="平台大促", target=None,
             start=date(2025, 4, 28), end=date(2025, 5, 5)),
        dict(name="2025年618", level="S", type="平台大促", target=None,
             start=date(2025, 5, 28), end=date(2025, 6, 20)),
        dict(name="冰洗节", level="B", type="品类促销", target="冰箱",
             start=date(2025, 7, 10), end=date(2025, 7, 14)),
        dict(name="818家电节", level="A", type="平台大促", target=None,
             start=date(2025, 8, 14), end=date(2025, 8, 18)),
        dict(name="冰箱品牌日", level="B", type="品类促销", target="冰箱",
             start=date(2025, 8, 16), end=date(2025, 8, 19)),   # 与 818 重叠！
        dict(name="金九家装节", level="B", type="品类促销", target="平板电视",
             start=date(2025, 9, 10), end=date(2025, 9, 15)),
        dict(name="国庆大促", level="A", type="平台大促", target=None,
             start=date(2025, 9, 28), end=date(2025, 10, 7)),
        dict(name="2025双11", level="S", type="平台大促", target=None,
             start=date(2025, 10, 25), end=date(2025, 11, 12)),
        dict(name="双12", level="A", type="平台大促", target=None,
             start=date(2025, 12, 5), end=date(2025, 12, 13)),
        # ---- 2026 手写 ----
        dict(name="2026年货节", level="S", type="平台大促", target=None,
             start=date(2026, 1, 15), end=date(2026, 1, 28)),
        dict(name="315家电周", level="A", type="平台大促", target=None,
             start=date(2026, 3, 10), end=date(2026, 3, 16)),
        dict(name="春季空调节", level="B", type="品类促销", target="空调",
             start=date(2026, 3, 20), end=date(2026, 3, 24), uplift=B_UPLIFT_2026),
        dict(name="2026年618", level="S", type="平台大促", target=None,
             start=date(2026, 5, 28), end=date(2026, 6, 18)),
        dict(name="冰洗焕新节", level="B", type="品类促销", target="冰箱",
             start=date(2026, 6, 25), end=date(2026, 6, 29), uplift=B_UPLIFT_2026),
        dict(name="818家电节", level="A", type="平台大促", target=None,
             start=date(2026, 8, 14), end=date(2026, 8, 18)),
    ]
    # ---- 2026 程序化 B 级轮动：每 5 天一场、每场 3 天、增量低（1.15）----
    # 复刻"促销密度大幅提升但单场效率下降"的现象
    rotate = ["空调", "冰箱", "洗衣机", "平板电视", "热水器", "手机", "冰箱", "洗衣机"]
    k = 0
    d = date(2026, 1, 5)
    while d <= date(2026, 8, 20):
        cat = rotate[k % len(rotate)]
        promos.append(dict(name=f"{cat}焕新节-{k + 1}", level="B", type="品类促销",
                           target=cat, start=d, end=d + timedelta(days=2),
                           theme=f"{cat}轮动", uplift=B_UPLIFT_2026))
        k += 1
        d += timedelta(days=5)
    # 补全 uplift / theme（对齐真实活动日历的 activity_theme 字段），并编号
    for i, p in enumerate(promos):
        p.setdefault("uplift", PROMO_MULT[p["level"]])
        p.setdefault("theme", p["name"])
        p["id"] = i + 1
    return promos


# ---------------------------------------------------------------- 3. 维度数据
def gen_dimensions(rng: random.Random):
    """生成品类/商品/用户/促销 四张维度表数据。"""
    categories = [(1, "大家电", None, 1), (2, "小家电", None, 1), (3, "手机数码", None, 1)]
    cat_map = {}   # 名称 -> category_id
    for cid, name, parent in CATEGORIES:
        categories.append((cid, name, parent, 2))
        cat_map[name] = cid

    products = []
    pid = 100001
    for cat, items in PRODUCTS_BY_CAT.items():
        for brand, name, price in items:
            products.append(dict(
                product_id=pid, product_name=f"{brand} {name}", brand=brand,
                category_id=cat_map[cat], list_price=D(price),
                launch_dt=date(2024, rng.randint(1, 12), rng.randint(1, 28)),
                is_active=1))
            pid += 1
    # 少量 2025-2026 上市新品
    for cat in ["空调", "手机", "平板电视"]:
        products.append(dict(
            product_id=pid, product_name=f"{cat}2026新款Pro", brand="新品",
            category_id=cat_map[cat], list_price=D(rng.randint(3000, 8000)),
            launch_dt=date(2026, rng.randint(1, 6), rng.randint(1, 28)),
            is_active=1))
        pid += 1

    users = []
    for uid in range(2000001, 2000001 + N_USERS):
        users.append(dict(
            user_id=uid,
            register_dt=date(2023, 1, 1) + timedelta(days=rng.randint(0, 1300)),
            city=rng.choice(CITIES),
            vip_level=rng.choices([0, 1, 2, 3], [0.70, 0.18, 0.09, 0.03])[0]))
    return categories, cat_map, products, users, build_promos()


# ---------------------------------------------------------------- 4. 事实数据主循环
def poisson(rng: random.Random, lam: float) -> int:
    """泊松抽样：lam 大时用正态近似（Knuth 算法在 lam>30 时太慢）。"""
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def cat_weight_for_day(day: date):
    """返回 {category_id: 权重}，季节系数 × 基础权重。"""
    m = day.month - 1
    w = {}
    for cid, name, _ in CATEGORIES:
        w[cid] = CAT_BASE_WEIGHT[name] * SEASONALITY[name][m]
    total = sum(w.values())
    return {c: v / total for c, v in w.items()}


def squeeze_factor(promos: list[dict], day: date) -> float:
    """当天的自然期挤压系数：活动当天 0.6；结束后按恢复天数线性回升。"""
    f = 1.0
    for p in promos:
        if p["start"] <= day <= p["end"]:
            f = min(f, SQUEEZE)
        else:
            off = (day - p["end"]).days
            rec = RECOVERY_DAYS[p["level"]]
            if 0 < off <= rec:   # 恢复期：线性 0.6 → 1.0
                f = min(f, SQUEEZE + (1 - SQUEEZE) * off / rec)
    return f


def fatigue_factor(promos: list[dict], day: date) -> float:
    """促销疲劳：活动开始前 2 天内自然需求被抑制（消费者等促销）。
    恢复期内不叠加疲劳，否则会掩盖 S 级大促的恢复曲线。"""
    for p in promos:
        off = (day - p["end"]).days
        if 0 < off <= RECOVERY_DAYS[p["level"]]:
            return 1.0
    for p in promos:
        if p["start"] <= day <= p["end"]:
            return 1.0
        if 0 < (p["start"] - day).days <= 2:
            return FATIGUE
    return 1.0


def uv_multiplier(promos: list[dict], cat_name: str | None, day: date) -> float:
    """UV 放大系数：活动中放大；结束后 4 天指数衰减尾巴。"""
    mult = 1.0
    for p in promos:
        covers = p["target"] is None or p["target"] == cat_name
        if not covers:
            continue
        m = TRAFFIC_MULT[p["level"]]
        if p["start"] <= day <= p["end"]:
            mult = max(mult, m)
        else:
            off = (day - p["end"]).days
            if 0 < off <= TRAFFIC_DECAY_DAYS:
                mult = max(mult, 1 + (m - 1) * (0.5 ** off))
    return mult


def gen_facts(rng: random.Random, cat_map, products, users, promos):
    orders, items, traffic_rows, refunds = [], [], [], []

    # 商品索引：category_id -> [products]（按上市时间过滤）
    by_cat = defaultdict(list)
    for p in products:
        by_cat[p["category_id"]].append(p)
    cat_names = {cid: name for cid, name, _ in CATEGORIES}
    cat_ids = [c for c, _, _ in CATEGORIES]

    total_days = (END - START).days + 1
    for i in range(total_days):
        day = START + timedelta(days=i)
        dow = day.weekday()
        m_idx = (day.year - 2025) * 12 + day.month - 1
        base = BASE_DAILY_ORDERS * WEEKLY[dow] * (1 + MONTHLY_TREND) ** m_idx
        if day.year == 2026:
            base *= DEMAND_2026   # 2026 需求疲软（促销常态化透支）

        active = [p for p in promos if p["start"] <= day <= p["end"]]
        sq = squeeze_factor(promos, day)
        fg = fatigue_factor(promos, day)

        # ---- 自然期订单（无 promo_id，受挤压 × 疲劳）----
        n_nat = poisson(rng, base * sq * fg)
        # ---- 促销订单（按每场活动独立叠加）----
        promo_orders = []   # (promo, count)
        for p in active:
            vol = base * p["uplift"] * (0.5 if p["target"] else 1.0)
            promo_orders.append((p, poisson(rng, vol)))

        weights = cat_weight_for_day(day)
        cats_list = cat_ids
        w_list = [weights[c] for c in cats_list]

        def pick_category(p=None):
            if p and p["target"] and rng.random() < 0.9:
                return cat_map[p["target"]]
            return rng.choices(cats_list, w_list)[0]

        for p, cnt in promo_orders + [(None, n_nat)]:
            for _ in range(cnt):
                cid = pick_category(p)
                # 下单用户与商品
                u = rng.choice(users)
                avail = [x for x in by_cat[cid] if x["launch_dt"] <= day]
                if not avail:
                    continue
                # 订单状态：92% 完成 / 5% 取消 / 3% 已退
                status = rng.choices(["completed", "cancelled", "refunded"],
                                     [0.92, 0.05, 0.03])[0]
                n_items = rng.choices([1, 2, 3], [0.55, 0.30, 0.15])[0]
                chosen = [rng.choice(avail) for _ in range(n_items)]
                # 明细：成交价 = 挂牌价 × 折扣（促销订单折扣更深）
                disc_lo = 0.80 if p else 0.88
                item_rows, pay = [], D(0)
                for prod in chosen:
                    qty = rng.choices([1, 2], [0.85, 0.15])[0]
                    price = (prod["list_price"]
                             * D(str(round(rng.uniform(disc_lo, 1.0), 2))))
                    price = price.quantize(D("0.01"))
                    gmv = (price * qty).quantize(D("0.01"))
                    item_rows.append(dict(order_id=None, product_id=prod["product_id"],
                                          qty=qty, price=price, gmv=gmv))
                    pay += gmv
                if status == "cancelled":
                    pay = D("0.00")   # 口径教学点：GMV 需过滤取消单
                order_id = len(orders) + 5000001
                # 支付时间：取消单无支付（NULL）；大促日 15% 概率跨天（口径坑）
                if status == "cancelled":
                    pay_dt = None
                elif p and p["level"] == "S" and rng.random() < 0.15:
                    pay_dt = day + timedelta(days=1, hours=rng.randint(0, 2))
                else:
                    pay_dt = day + timedelta(hours=rng.randint(8, 23))
                channel = None
                if day >= CHANNEL_NULL_BEFORE:
                    channel = rng.choices([c for c, _ in CHANNELS],
                                          [w for _, w in CHANNELS])[0]
                orders.append(dict(
                    order_id=order_id, user_id=u["user_id"], order_dt=day,
                    pay_dt=pay_dt, pay_amt=pay, item_cnt=n_items,
                    order_status=status, channel=channel,
                    promo_id=(p["id"] if p else None)))
                for it in item_rows:
                    it["order_id"] = order_id
                items.extend(item_rows)

        # ---- 流量：每个二级品类一行 ----
        for cid in cat_ids:
            name = cat_names[cid]
            uv = (BASE_UV[name] * SEASONALITY[name][day.month - 1]
                  * (1.15 if dow >= 5 else 1.0)
                  * uv_multiplier(promos, name, day))
            uv = max(int(round(uv * rng.uniform(0.9, 1.1))), 100)
            pv = int(uv * rng.uniform(2.8, 4.2))
            in_promo = any(p["target"] in (None, name)
                           and p["start"] <= day <= p["end"] for p in promos)
            cart = int(uv * rng.uniform(0.06, 0.16) * (1.3 if in_promo else 1.0))
            traffic_rows.append(dict(dt=day, category_id=cid, uv=uv, pv=pv, cart_cnt=cart))

    # ---- 退货：3% 完成单生成退款记录 ----
    refund_rows = []
    for o in orders:
        if o["order_status"] == "refunded":
            refund_rows.append(dict(
                refund_id=None, order_id=o["order_id"],
                refund_dt=o["order_dt"] + timedelta(days=rng.randint(1, 14)),
                refund_amt=(o["pay_amt"]
                            * D(str(round(rng.uniform(0.5, 1.0), 2)))).quantize(D("0.01")),
                refund_reason=rng.choice(["质量问题", "七天无理由", "价格保护", "物流破损", "不想要了"])))
    return orders, items, traffic_rows, refund_rows


# ---------------------------------------------------------------- 5. 脏数据注入
def inject_dirt(rng: random.Random, orders, items, refund_rows, promos):
    """注入已知脏数据；同时返回一个"已知答案"清单用于核对。"""
    dirt = {}

    # a. 3 条退款时间早于下单
    for r in refund_rows[:3]:
        o = next(x for x in orders if x["order_id"] == r["order_id"])
        r["refund_dt"] = o["order_dt"] - timedelta(days=1)
    dirt["refund_时间矛盾"] = 3

    # b. 2 条明细单价放大 100 倍（单位漂移 → 对账不平）
    #    必须选非取消单的明细（否则过滤取消单后对账差异不可见），
    #    且分属两个不同订单（对账时"2 个订单不平"与"2 条脏明细"一一对应）
    status_of = {o["order_id"]: o["order_status"] for o in orders}
    dirty_items, seen_orders = [], set()
    for it in items:
        oid = it["order_id"]
        if status_of[oid] == "cancelled" or oid in seen_orders:
            continue
        dirty_items.append(it)
        seen_orders.add(oid)
        if len(dirty_items) == 2:
            break
    delta = D(0)
    for it in dirty_items:
        delta += it["price"] * 99 * it["qty"]   # 放大前后的差额
        it["price"] *= 100
        it["gmv"] = it["price"] * it["qty"]
    dirt["price_漂移"] = len(dirty_items)
    dirt["price_漂移预期差额(元)"] = f"{delta:.2f}"

    # c. ~0.2% 促销订单归属漂移：order_dt 挪到活动结束后一天
    n = max(1, int(len(orders) * 0.002))
    cnt = 0
    for o in orders:
        if cnt >= n:
            break
        if o["promo_id"]:
            p = promos[o["promo_id"] - 1]
            shift = (p["end"] + timedelta(days=1)) - o["order_dt"]
            o["order_dt"] += shift
            # 取消单无支付时间，漂移时保持 NULL（否则连锁产生"取消单有 pay_dt"异常）
            if o["order_status"] != "cancelled":
                o["pay_dt"] = o["order_dt"] + timedelta(hours=rng.randint(8, 23))
            # 退款时间随订单平移（保持退款滞后天数不变），
            # 否则会连锁产生大量 refund_dt < order_dt 的矛盾行
            for r in refund_rows:
                if r["order_id"] == o["order_id"]:
                    r["refund_dt"] += shift
            cnt += 1
    dirt["promo归属漂移"] = cnt

    # d. 1 个已退单没有退款记录（关联丢行）；避开 a 注入的前 3 条，保持陷阱相互独立
    dirtied_orders = {refund_rows[i]["order_id"] for i in range(3)}
    victim = next(o for o in orders
                  if o["order_status"] == "refunded"
                  and o["order_id"] not in dirtied_orders)
    refund_rows[:] = [r for r in refund_rows if r["order_id"] != victim["order_id"]]
    dirt["refund_关联丢行"] = 1

    return dirt


# ---------------------------------------------------------------- 6. 入库
def insert_db(conn, categories, products, users, promos,
              orders, items, traffic_rows, refund_rows):
    cur = conn.cursor()
    for t in ["refunds", "order_items", "orders", "traffic", "promo_calendar",
              "products", "users", "categories"]:
        cur.execute(f"DELETE FROM {t}")
    cur.executemany(
        "INSERT INTO categories VALUES (%s,%s,%s,%s)", categories)
    cur.executemany(
        "INSERT INTO products VALUES (%s,%s,%s,%s,%s,%s,%s)",
        [(p["product_id"], p["product_name"], p["brand"], p["category_id"],
          p["list_price"], p["launch_dt"], p["is_active"]) for p in products])
    cur.executemany(
        "INSERT INTO users VALUES (%s,%s,%s,%s)",
        [(u["user_id"], u["register_dt"], u["city"], u["vip_level"]) for u in users])
    cur.executemany(
        "INSERT INTO promo_calendar "
        "(promo_id, promo_name, level, promo_type, start_dt, end_dt, "
        "activity_theme, duration_days) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        [(p["id"], p["name"], p["level"], p["type"], p["start"], p["end"],
          p["theme"], (p["end"] - p["start"]).days + 1) for p in promos])
    for i in range(0, len(orders), 5000):
        batch = orders[i:i + 5000]
        cur.executemany(
            "INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(o["order_id"], o["user_id"], o["order_dt"], o["pay_dt"], o["pay_amt"],
              o["item_cnt"], o["order_status"], o["channel"], o["promo_id"])
             for o in batch])
    for i in range(0, len(items), 5000):
        batch = items[i:i + 5000]
        cur.executemany(
            "INSERT INTO order_items (order_id, product_id, qty, price, gmv) "
            "VALUES (%s,%s,%s,%s,%s)",
            [(it["order_id"], it["product_id"], it["qty"], it["price"], it["gmv"])
             for it in batch])
    for i in range(0, len(traffic_rows), 5000):
        batch = traffic_rows[i:i + 5000]
        cur.executemany(
            "INSERT INTO traffic VALUES (%s,%s,%s,%s,%s)",
            [(t["dt"], t["category_id"], t["uv"], t["pv"], t["cart_cnt"])
             for t in batch])
    for i, r in enumerate(refund_rows):
        r["refund_id"] = i + 1
    for i in range(0, len(refund_rows), 5000):
        batch = refund_rows[i:i + 5000]
        cur.executemany(
            "INSERT INTO refunds VALUES (%s,%s,%s,%s,%s)",
            [(r["refund_id"], r["order_id"], r["refund_dt"], r["refund_amt"],
              r["refund_reason"]) for r in batch])
    conn.commit()
    cur.close()


# ---------------------------------------------------------------- 7. 统计摘要（已知答案）
def print_summary(orders, items, traffic_rows, refund_rows, promos, dirt):
    from collections import OrderedDict
    print("\n" + "=" * 64)
    print("统计摘要（这批数据的『已知答案』，检验 agent 时用）")
    print("=" * 64)

    # 7.1 行数
    print("\n[行数]")
    print(f"  orders={len(orders):,}  order_items={len(items):,}  "
          f"traffic={len(traffic_rows):,}  refunds={len(refund_rows):,}")

    # 7.2 月度 GMV（万元，过滤取消单）
    monthly = OrderedDict()
    for o in orders:
        if o["order_status"] == "cancelled":
            continue
        key = o["order_dt"].strftime("%Y-%m")
        monthly.setdefault(key, [D(0), D(0)])       # [总, 促销]
        monthly[key][0] += o["pay_amt"]
        if o["promo_id"]:
            monthly[key][1] += o["pay_amt"]
    print("\n[月度GMV/万元（过滤取消单）]")
    for k, (tot, pro) in monthly.items():
        share = pro / tot * 100 if tot else 0
        print(f"  {k}  总 {tot/10000:10.2f}  促销占比 {share:5.1f}%")

    def half_gmv(ym_lo, ym_hi):
        tot = pro = D(0)
        for k, (t, p) in monthly.items():
            if ym_lo <= k <= ym_hi:
                tot += t
                pro += p
        return tot, pro

    h1_25, p1_25 = half_gmv("2025-01", "2025-06")
    h1_26, p1_26 = half_gmv("2026-01", "2026-06")
    print("\n[核心故事：促销密度提升、总GMV下滑？]")
    print(f"  2025H1 总GMV {h1_25/10000:10.2f}万  促销GMV {p1_25/10000:10.2f}万"
          f"  占比 {p1_25/h1_25*100:5.1f}%")
    print(f"  2026H1 总GMV {h1_26/10000:10.2f}万  促销GMV {p1_26/10000:10.2f}万"
          f"  占比 {p1_26/h1_26*100:5.1f}%")
    if h1_25:
        print(f"  同比变化 {(h1_26/h1_25-1)*100:+.1f}%")

    # 7.3 促销密度
    def density(lo, hi):
        days = (hi - lo).days + 1
        active_days = sum(1 for i in range(days)
                          if any(p["start"] <= lo + timedelta(days=i) <= p["end"]
                                 for p in promos))
        return active_days / days * 100
    print("\n[促销密度]")
    print(f"  2025H1 {density(date(2025,1,1), date(2025,6,30)):.1f}%  "
          f"2026H1 {density(date(2026,1,1), date(2026,6,30)):.1f}%")

    # 7.4 B 级活动效率（2025 vs 2026）：2026 场次更多但单场更弱
    by_promo = defaultdict(D)
    for o in orders:
        if o["promo_id"] and o["order_status"] != "cancelled":
            by_promo[o["promo_id"]] += o["pay_amt"]
    print("\n[B级活动效率对比（2025 vs 2026）]")
    for year in (2025, 2026):
        ps = [p for p in promos if p["level"] == "B" and p["start"].year == year]
        days = sum((p["end"] - p["start"]).days + 1 for p in ps)
        gmv = sum(by_promo[p["id"]] for p in ps)
        avg_uplift = sum(p["uplift"] for p in ps) / len(ps)
        print(f"  {year}: {len(ps):2d} 场 / 促销天数 {days:3d} / "
              f"日均促销GMV {gmv/days/10000:8.2f}万 / 场均uplift {avg_uplift:.2f}")

    # 7.5 S 级恢复期（同星期基线归一，剔除被其他活动打断的天）
    #     比值 = 当日自然GMV / (同星期基线 × AOV)，应呈 0.55→1.0 回升
    natural_by_day = defaultdict(D)
    for o in orders:
        if o["promo_id"] is None and o["order_status"] != "cancelled":
            natural_by_day[o["order_dt"]] += o["pay_amt"]
    n_nat_orders = sum(1 for o in orders
                       if o["promo_id"] is None and o["order_status"] != "cancelled")
    aov = sum(natural_by_day.values()) / D(str(n_nat_orders))

    def base_for(day: date) -> float:
        m_idx = (day.year - 2025) * 12 + day.month - 1
        b = BASE_DAILY_ORDERS * WEEKLY[day.weekday()] * (1 + MONTHLY_TREND) ** m_idx
        return b * (DEMAND_2026 if day.year == 2026 else 1.0)

    print("\n[S级活动结束后的自然期恢复（比值=当日自然GMV/同星期基线，应 0.55→1.0 回升）]")
    for year in (2025, 2026):
        buckets = {b: [] for b in [(1, 3), (4, 5), (6, 8)]}
        s_promos = [p for p in promos if p["level"] == "S" and p["start"].year == year]
        for p in s_promos:
            for off in range(1, RECOVERY_DAYS["S"] + 1):
                day = p["end"] + timedelta(days=off)
                others = [x for x in promos if x is not p]   # 排除活动自身
                if squeeze_factor(others, day) < 1.0 or fatigue_factor(others, day) < 1.0:
                    continue   # 当天被其他活动覆盖，不属于"干净"恢复日
                ratio = natural_by_day.get(day, D(0)) / (D(str(base_for(day))) * aov)
                for (lo, hi), lst in buckets.items():
                    if lo <= off <= hi:
                        lst.append(ratio)
        line = f"  {year} S级({len(s_promos)}场合计): "
        for (lo, hi), lst in buckets.items():
            if lst:
                line += f"{lo}-{hi}天 {sum(lst)/len(lst)*100:5.0f}%  "
            else:
                line += f"{lo}-{hi}天   —  "
        if not any(buckets.values()):
            line += "  ← 恢复期被轮动B级促销完全打断"
        print(line)

    # 7.6 脏数据核对
    print("\n[脏数据核对（生成器注入的『陷阱』）]")
    for k, v in dirt.items():
        print(f"  {k}: {v}")

    # 7.7 对账（正确口径：明细侧也过滤取消单，两边才可比）
    keep = {o["order_id"] for o in orders if o["order_status"] != "cancelled"}
    pay_sum = sum(o["pay_amt"] for o in orders if o["order_id"] in keep)
    item_sum = sum(i["gmv"] for i in items if i["order_id"] in keep)
    diff = item_sum - pay_sum
    print("\n[对账]")
    print(f"  orders.pay_amt 合计(过滤取消) = {pay_sum/10000:12.2f}万")
    print(f"  order_items.gmv 合计(同口径) = {item_sum/10000:12.2f}万")
    print(f"  差额 = {diff:.2f} 元（应等于 price_漂移预期差额，非 0）")


# ---------------------------------------------------------------- 8. 主入口
def main():
    ap = argparse.ArgumentParser(description="生成并入库模拟数据")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--dry-run", action="store_true", help="只生成+打印统计，不连库")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default=None)
    ap.add_argument("--db", default="jd_demo")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    print(f"生成维度数据（seed={args.seed}）...")
    categories, cat_map, products, users, promos = gen_dimensions(rng)
    print(f"  品类 {len(categories)-3} 二级 / 商品 {len(products)} / "
          f"用户 {len(users):,} / 促销 {len(promos)} 场")
    print("生成事实数据（2025-01-01 ~ 2026-08-31，约 1~3 分钟）...")
    orders, items, traffic_rows, refund_rows = gen_facts(rng, cat_map, products,
                                                         users, promos)
    dirt = inject_dirt(rng, orders, items, refund_rows, promos)
    print(f"  订单 {len(orders):,} / 明细 {len(items):,} / "
          f"流量 {len(traffic_rows):,} / 退款 {len(refund_rows):,}")

    if not args.dry_run:
        import pymysql
        pw = args.password or getpass.getpass("root 密码: ")
        conn = pymysql.connect(host=args.host, port=args.port, user=args.user,
                               password=pw, database=args.db, charset="utf8mb4")
        print("入库中...")
        insert_db(conn, categories, products, users, promos,
                  orders, items, traffic_rows, refund_rows)
        conn.close()
        print("入库完成。")
    print_summary(orders, items, traffic_rows, refund_rows, promos, dirt)


if __name__ == "__main__":
    main()
