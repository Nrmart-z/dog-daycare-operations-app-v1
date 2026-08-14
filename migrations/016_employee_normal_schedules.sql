CREATE TABLE IF NOT EXISTS employee_normal_schedules (
    user_id INT NOT NULL,
    weekday_number TINYINT NOT NULL,
    period VARCHAR(2) NOT NULL,
    shift_label VARCHAR(120) NOT NULL,
    updated_by_user_id INT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, weekday_number, period),
    CONSTRAINT fk_normal_schedule_user FOREIGN KEY (user_id) REFERENCES staff_users (user_id),
    CONSTRAINT fk_normal_schedule_editor FOREIGN KEY (updated_by_user_id) REFERENCES staff_users (user_id)
);
