-- 升级前停止服务并备份 lesslab 数据库。先完成 001—004，仅执行本脚本一次。
-- MySQL DDL 不保证整份脚本原子提交；如中途报错，先检查已创建表/列，不要盲目重跑。
USE lesslab;

CREATE TABLE users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    password_hash VARCHAR(180) CHARACTER SET ascii NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_sessions (
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    csrf_token VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    expires_at BIGINT NOT NULL,
    INDEX idx_sessions_user (user_id),
    INDEX idx_sessions_expiry (expires_at),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE auth_control (
    id TINYINT UNSIGNED PRIMARY KEY,
    owner_id BIGINT UNSIGNED NULL,
    CHECK (id = 1),
    FOREIGN KEY (owner_id) REFERENCES users(id)
);
INSERT INTO auth_control(id) VALUES(1);

CREATE TABLE auth_throttle (
    bucket_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    attempts INT UNSIGNED NOT NULL,
    window_start BIGINT NOT NULL,
    INDEX idx_throttle_expiry (window_start)
);

CREATE TABLE user_goals (
    user_id BIGINT UNSIGNED PRIMARY KEY,
    title VARCHAR(200) NULL,
    success_criteria VARCHAR(250) NOT NULL DEFAULT '',
    due_date DATE NULL,
    daily_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 30,
    version INT UNSIGNED NOT NULL DEFAULT 0,
    CHECK (daily_minutes BETWEEN 1 AND 600),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

ALTER TABLE resources
    ADD COLUMN owner_id BIGINT UNSIGNED NULL,
    ADD INDEX idx_resources_owner (owner_id, id),
    ADD CONSTRAINT fk_resources_owner FOREIGN KEY (owner_id) REFERENCES users(id);

ALTER TABLE study_plans
    ADD COLUMN owner_id BIGINT UNSIGNED NULL,
    ADD INDEX idx_plans_owner (owner_id, id),
    ADD CONSTRAINT fk_plans_owner FOREIGN KEY (owner_id) REFERENCES users(id);

-- 旧记录暂时 owner_id=NULL，所有网页账号都看不到。随后在本机运行 setup_owner.py。
-- study_plan_progress 通过其 plan_id 所属计划隔离；不删除或改写历史快照。
-- 旧 current_goal 表保留作为迁移来源，运行中的新接口只读写 user_goals。
