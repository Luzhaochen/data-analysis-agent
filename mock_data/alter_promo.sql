-- ============================================================
-- promo_calendar 增量加列（已建好 8 张表后执行本文件，root 执行）
-- 对齐真实活动日历（DataWorks 导出）字段形态：
--   activity_theme 活动主题、duration_days 活动天数
-- ============================================================
USE jd_demo;

ALTER TABLE promo_calendar
  ADD COLUMN activity_theme VARCHAR(64) NULL
    COMMENT '活动主题（对齐真实活动日历字段，如 年货节/品类轮动）' AFTER promo_type,
  ADD COLUMN duration_days INT NULL
    COMMENT '活动天数（含首尾）；真实导出中可能是字符串（如 1小时），接入时需清洗'
    AFTER end_dt;

-- 验证
-- SHOW COLUMNS FROM promo_calendar;
