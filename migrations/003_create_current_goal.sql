-- 当前单用户原型只保存一份当前目标。重复执行不会覆盖已有目标。
USE lesslab;
CREATE TABLE IF NOT EXISTS current_goal (
    id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    title VARCHAR(200) NULL,
    success_criteria VARCHAR(250) NOT NULL DEFAULT '',
    due_date DATE NULL,
    daily_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 30,
    version INT UNSIGNED NOT NULL DEFAULT 0,
    CONSTRAINT chk_current_goal_singleton CHECK (id = 1),
    CONSTRAINT chk_current_goal_minutes CHECK (daily_minutes BETWEEN 1 AND 600)
);
INSERT INTO current_goal (id)
SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM current_goal WHERE id = 1);
