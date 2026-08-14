CREATE TABLE IF NOT EXISTS schedule_holidays (
    holiday_date DATE NOT NULL,
    holiday_name VARCHAR(120) NULL,
    created_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (holiday_date),
    CONSTRAINT fk_holiday_creator FOREIGN KEY (created_by_user_id)
        REFERENCES staff_users (user_id)
);
