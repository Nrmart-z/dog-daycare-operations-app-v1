CREATE TABLE IF NOT EXISTS shift_trade_requests (
    trade_request_id INT NOT NULL AUTO_INCREMENT,
    requester_user_id INT NOT NULL,
    target_user_id INT NOT NULL,
    requester_shift_id INT NOT NULL,
    target_shift_id INT NOT NULL,
    request_note VARCHAR(500) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at DATETIME NULL,
    PRIMARY KEY (trade_request_id),
    KEY idx_trade_target_status (target_user_id, status, created_at),
    KEY idx_trade_requester (requester_user_id, created_at),
    CONSTRAINT fk_trade_requester FOREIGN KEY (requester_user_id) REFERENCES staff_users (user_id),
    CONSTRAINT fk_trade_target FOREIGN KEY (target_user_id) REFERENCES staff_users (user_id),
    CONSTRAINT fk_trade_requester_shift FOREIGN KEY (requester_shift_id) REFERENCES work_shifts (shift_id),
    CONSTRAINT fk_trade_target_shift FOREIGN KEY (target_shift_id) REFERENCES work_shifts (shift_id)
);
