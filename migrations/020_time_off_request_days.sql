CREATE TABLE IF NOT EXISTS time_off_request_days (
    request_day_id INT NOT NULL AUTO_INCREMENT,
    request_id INT NOT NULL,
    request_date DATE NOT NULL,
    period VARCHAR(10) NOT NULL,
    PRIMARY KEY (request_day_id),
    UNIQUE KEY uq_time_off_request_day (request_id, request_date),
    KEY idx_time_off_day_date (request_date),
    CONSTRAINT fk_time_off_day_request FOREIGN KEY (request_id)
        REFERENCES time_off_requests (request_id) ON DELETE CASCADE
);

INSERT IGNORE INTO time_off_request_days (request_id, request_date, period)
SELECT request_id, start_date, period
FROM time_off_requests
WHERE start_date = end_date;
