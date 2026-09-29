USE lesslab;

-- 任务编号来自保存的计划快照，不依赖收藏是否仍存在或已归档。
CREATE TABLE IF NOT EXISTS study_plan_progress (
    plan_id BIGINT UNSIGNED NOT NULL,
    resource_id INT UNSIGNED NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at DATETIME NULL,
    PRIMARY KEY (plan_id, resource_id),
    CONSTRAINT fk_progress_plan FOREIGN KEY (plan_id) REFERENCES study_plans(id),
    CONSTRAINT chk_progress_completed CHECK (completed IN (0, 1)),
    CONSTRAINT chk_progress_time CHECK (
        (completed = 0 AND completed_at IS NULL) OR
        (completed = 1 AND completed_at IS NOT NULL)
    )
);
