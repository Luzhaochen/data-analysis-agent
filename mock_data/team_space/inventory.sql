-- ============================================================
-- 库存快照表（业务方新建，2026-09 上线）
-- 用途：各仓库各商品的每日库存快照，支撑缺货/补货/周转分析
-- 执行：root 在 jd_demo 库上执行本文件
-- ============================================================
CREATE TABLE inventory (
  inventory_id BIGINT      NOT NULL AUTO_INCREMENT COMMENT '库存记录ID',
  product_id   BIGINT      NOT NULL COMMENT '商品ID（关联 products）',
  warehouse    VARCHAR(32) NOT NULL COMMENT '仓库：华北仓/华东仓/华南仓/西南仓',
  stock_qty    INT         NOT NULL COMMENT '库存数量（件）',
  dt           DATE        NOT NULL COMMENT '库存快照日期（分区字段）',
  PRIMARY KEY (inventory_id),
  KEY idx_product_dt (product_id, dt),
  KEY idx_dt (dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='库存快照表：一行一天一商品一仓库，用于缺货/补货分析';
