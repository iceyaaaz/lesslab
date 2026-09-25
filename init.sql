-- 创建项目数据库
CREATE DATABASE IF NOT EXISTS lesslab
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE lesslab;

-- 创建收藏表
CREATE TABLE IF NOT EXISTS resources (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    url TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'unread',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    estimated_minutes SMALLINT UNSIGNED NULL
        COMMENT '预计学习分钟数，NULL表示尚未填写'
);