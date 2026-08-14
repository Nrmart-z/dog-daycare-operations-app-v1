CREATE TABLE daily_assignment_records (
    record_id INT NOT NULL AUTO_INCREMENT,
    record_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Finalized',
    revision_number INT NOT NULL DEFAULT 1,
    finalized_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_reason VARCHAR(200) NULL,
    PRIMARY KEY (record_id),
    UNIQUE KEY uq_daily_assignment_record_date (record_date)
);
