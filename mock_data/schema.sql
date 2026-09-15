-- ============================================================
-- DataAnalysis 数据分析智能体 · 模拟数据表结构（京东大家电风格）
-- 执行方式：root 执行本文件即可（脚本会自动创建 jd_demo 库）
--
-- 设计要点：
--   1. 每张表/每个字段都写 COMMENT —— information_schema 能读出来，
--      get_metadata.py 建档时直接成为知识库草稿的初始内容
--   2. 故意埋的口径教学点（对应知识库"注意事项"）：
--      a. orders 与 order_items 是 1:N，跨表聚合必须先按 order_id 去重
--      b. orders.pay_amt 应等于 order_items.gmv 按订单汇总（可对账）
--      c. promo_calendar 存在活动区间重叠（订单归属口径）
--      d. channel 在 2025-06 前为 NULL（历史字段缺失）
--      e. refunds 会注入少量脏数据（refund_dt 早于 order_dt）
-- ============================================================

CREATE DATABASE IF NOT EXISTS jd_demo CHARACTER SET utf8mb4;
USE jd_demo;

-- 1. 品类表（一级/二级）
DROP TABLE IF EXISTS categories;
CREATE TABLE categories (
  category_id    INT          NOT NULL AUTO_INCREMENT COMMENT '品类ID',
  category_name  VARCHAR(64)  NOT NULL COMMENT '品类名称',
  parent_id      INT          NULL COMMENT '父品类ID，NULL=一级品类',
  category_level TINYINT      NOT NULL COMMENT '1=一级品类 2=二级品类',
  PRIMARY KEY (category_id),
  KEY idx_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='品类维度表';

-- 2. 商品表
DROP TABLE IF EXISTS products;
CREATE TABLE products (
  product_id   BIGINT        NOT NULL COMMENT '商品ID（SKU）',
  product_name VARCHAR(128)  NOT NULL COMMENT '商品名称',
  brand        VARCHAR(64)   NOT NULL COMMENT '品牌',
  category_id  INT           NOT NULL COMMENT '所属二级品类ID',
  list_price   DECIMAL(10,2) NOT NULL COMMENT '挂牌价（元）',
  launch_dt    DATE          NOT NULL COMMENT '上市日期',
  is_active    TINYINT(1)    NOT NULL DEFAULT 1 COMMENT '1=在售 0=下架',
  PRIMARY KEY (product_id),
  KEY idx_category (category_id),
  KEY idx_brand (brand)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品维度表';

-- 3. 用户表
DROP TABLE IF EXISTS users;
CREATE TABLE users (
  user_id     BIGINT       NOT NULL COMMENT '用户ID',
  register_dt DATE         NOT NULL COMMENT '注册日期',
  city        VARCHAR(32)  NOT NULL COMMENT '所在城市',
  vip_level   TINYINT      NOT NULL DEFAULT 0 COMMENT '0=普通 1=银牌 2=金牌 3=钻石',
  PRIMARY KEY (user_id),
  KEY idx_city (city),
  KEY idx_register (register_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户维度表';

-- 4. 订单主表（一行一订单）
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
  order_id     BIGINT         NOT NULL COMMENT '订单号',
  user_id      BIGINT         NOT NULL COMMENT '下单用户ID',
  order_dt     DATE           NOT NULL COMMENT '下单日期（分区/时间过滤字段）',
  pay_dt       DATETIME       NULL COMMENT '支付时间；大促日可能跨天，口径归属按下单日',
  pay_amt      DECIMAL(12,2)  NOT NULL COMMENT '实付金额=明细gmv合计（可对账）',
  item_cnt     INT            NOT NULL COMMENT '订单明细行数',
  order_status VARCHAR(16)    NOT NULL COMMENT 'completed=完成 cancelled=取消 refunded=已退',
  channel      VARCHAR(16)    NULL COMMENT '下单渠道 app/pc/miniprogram；2025-06前为NULL',
  promo_id     BIGINT         NULL COMMENT '参与促销活动ID，NULL=自然期订单',
  PRIMARY KEY (order_id),
  KEY idx_order_dt (order_dt),
  KEY idx_user (user_id),
  KEY idx_promo (promo_id),
  KEY idx_status (order_status),
  KEY idx_channel (channel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单主表：一行一订单，明细在 order_items';

-- 5. 订单明细表（一行一SKU）
DROP TABLE IF EXISTS order_items;
CREATE TABLE order_items (
  item_id    BIGINT        NOT NULL AUTO_INCREMENT COMMENT '明细行ID',
  order_id   BIGINT        NOT NULL COMMENT '订单号（与 orders 1:N）',
  product_id BIGINT        NOT NULL COMMENT '商品ID',
  qty        INT           NOT NULL COMMENT '购买数量',
  price      DECIMAL(10,2) NOT NULL COMMENT '成交单价（元）',
  gmv        DECIMAL(12,2) NOT NULL COMMENT '该行成交额（元），行级口径',
  PRIMARY KEY (item_id),
  KEY idx_order (order_id),
  KEY idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单明细表：一行一SKU，跨表聚合需先去重';

-- 6. 促销日历表
DROP TABLE IF EXISTS promo_calendar;
CREATE TABLE promo_calendar (
  promo_id       BIGINT       NOT NULL AUTO_INCREMENT COMMENT '促销活动ID',
  promo_name     VARCHAR(64)  NOT NULL COMMENT '活动名称',
  level          CHAR(1)      NOT NULL COMMENT '活动等级 S/A/B',
  promo_type     VARCHAR(32)  NOT NULL COMMENT '平台大促/品类促销/品牌日',
  activity_theme VARCHAR(64)  NULL COMMENT '活动主题（对齐真实活动日历字段，如 年货节/品类轮动）',
  start_dt       DATE         NOT NULL COMMENT '开始日期（含）',
  end_dt         DATE         NOT NULL COMMENT '结束日期（含）',
  duration_days  INT          NULL COMMENT '活动天数（含首尾）；真实导出中可能是字符串（如 1小时）',
  PRIMARY KEY (promo_id),
  KEY idx_range (start_dt, end_dt),
  KEY idx_level (level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='促销日历：活动区间可能重叠，订单归属口径见知识库';

-- 7. 流量表（一行一天一二级品类）
DROP TABLE IF EXISTS traffic;
CREATE TABLE traffic (
  dt          DATE   NOT NULL COMMENT '日期（分区字段）',
  category_id INT    NOT NULL COMMENT '二级品类ID',
  uv          BIGINT NOT NULL COMMENT '独立访客数',
  pv          BIGINT NOT NULL COMMENT '页面浏览量',
  cart_cnt    INT    NOT NULL COMMENT '加购数',
  PRIMARY KEY (dt, category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='流量表：一行一天一品类，可算转化率';

-- 8. 退货表
DROP TABLE IF EXISTS refunds;
CREATE TABLE refunds (
  refund_id      BIGINT        NOT NULL COMMENT '退款单ID',
  order_id       BIGINT        NOT NULL COMMENT '原订单号',
  refund_dt      DATE          NOT NULL COMMENT '退款日期',
  refund_amt     DECIMAL(12,2) NOT NULL COMMENT '退款金额（元）',
  refund_reason  VARCHAR(64)   NOT NULL COMMENT '退款原因',
  PRIMARY KEY (refund_id),
  KEY idx_order (order_id),
  KEY idx_dt (refund_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='退货表：含少量脏数据用于结果校验演示';

-- 验证：执行后应看到 8 张表
-- SHOW TABLES;
