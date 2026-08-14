CREATE TABLE IF NOT EXISTS bug_reports (
    report_id INT NOT NULL AUTO_INCREMENT,
    report_type VARCHAR(30) NOT NULL,
    page_name VARCHAR(50) NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
    title VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    expected_behavior TEXT NULL,
    actual_behavior TEXT NULL,
    related_dog VARCHAR(100) NULL,
    related_room VARCHAR(50) NULL,
    reporter_name VARCHAR(100) NULL,
    report_status VARCHAR(20) NOT NULL DEFAULT 'New',
    app_version VARCHAR(20) NOT NULL DEFAULT '1.0.1',
    resolution_notes TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME NULL,
    PRIMARY KEY (report_id),
    KEY idx_bug_reports_status_priority (
        report_status,
        priority,
        created_at
    )
);
