USE lesslab;

CREATE TABLE IF NOT EXISTS study_plans (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    goal VARCHAR(500) NOT NULL,
    budget_minutes SMALLINT UNSIGNED NOT NULL,
    total_minutes SMALLINT UNSIGNED NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'ai',
    items JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_study_plan_budget
        CHECK (
            budget_minutes BETWEEN 1 AND 600
            AND total_minutes <= budget_minutes
        ),

    CONSTRAINT chk_study_plan_items
        CHECK (JSON_TYPE(items) = 'ARRAY')
);