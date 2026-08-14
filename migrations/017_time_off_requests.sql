CREATE TABLE IF NOT EXISTS time_off_requests (
    request_id INT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    period VARCHAR(10) NOT NULL,
    request_note VARCHAR(500) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    reviewed_by_user_id INT NULL,
    review_note VARCHAR(500) NULL,
    reviewed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (request_id),
    KEY idx_time_off_status (status, start_date),
    KEY idx_time_off_user (user_id, created_at),
    CONSTRAINT fk_time_off_user FOREIGN KEY (user_id) REFERENCES staff_users (user_id),
    CONSTRAINT fk_time_off_reviewer FOREIGN KEY (reviewed_by_user_id) REFERENCES staff_users (user_id)
);
