-- 已有数据库升级：使用有 ALTER 权限的管理员连接执行一次。
-- 若出现 Duplicate column name 'archived_at'，请先检查该字段是否已经存在。
USE lesslab;
ALTER TABLE resources
    ADD COLUMN archived_at DATETIME NULL DEFAULT NULL
    COMMENT '归档时间；NULL 表示未归档，原学习状态保留';
