CREATE TABLE IF NOT EXISTS staff_users (
    user_id INT NOT NULL AUTO_INCREMENT,
    username VARCHAR(80) NOT NULL,
    first_name VARCHAR(60) NOT NULL,
    last_name VARCHAR(60) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    must_change_password TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at DATETIME NULL,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_staff_username (username),
    KEY idx_staff_role_active (role, active)
);

CREATE TABLE IF NOT EXISTS operations_tasks (
    task_id INT NOT NULL AUTO_INCREMENT,
    title VARCHAR(160) NOT NULL,
    details VARCHAR(1000) NULL,
    department VARCHAR(20) NOT NULL,
    task_type VARCHAR(30) NOT NULL DEFAULT 'General',
    priority VARCHAR(20) NOT NULL DEFAULT 'Normal',
    due_at DATETIME NOT NULL,
    dog_id INT NULL,
    assigned_user_id INT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'Open',
    completion_note VARCHAR(500) NULL,
    completed_by_user_id INT NULL,
    completed_at DATETIME NULL,
    created_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (task_id),
    KEY idx_task_due_status (due_at, status),
    KEY idx_task_department_due (department, due_at),
    CONSTRAINT fk_task_dog FOREIGN KEY (dog_id) REFERENCES dogs_info (dog_id),
    CONSTRAINT fk_task_assignee FOREIGN KEY (assigned_user_id) REFERENCES staff_users (user_id),
    CONSTRAINT fk_task_completed_by FOREIGN KEY (completed_by_user_id) REFERENCES staff_users (user_id),
    CONSTRAINT fk_task_created_by FOREIGN KEY (created_by_user_id) REFERENCES staff_users (user_id)
);

CREATE TABLE IF NOT EXISTS work_shifts (
    shift_id INT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NOT NULL,
    department VARCHAR(20) NOT NULL,
    notes VARCHAR(300) NULL,
    created_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (shift_id),
    KEY idx_shift_start (starts_at),
    KEY idx_shift_user_start (user_id, starts_at),
    CONSTRAINT fk_shift_user FOREIGN KEY (user_id) REFERENCES staff_users (user_id),
    CONSTRAINT fk_shift_creator FOREIGN KEY (created_by_user_id) REFERENCES staff_users (user_id)
);

CREATE TABLE IF NOT EXISTS operations_audit_log (
    audit_id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NULL,
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(40) NOT NULL,
    entity_id VARCHAR(80) NULL,
    details VARCHAR(1000) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (audit_id),
    KEY idx_audit_created (created_at),
    KEY idx_audit_entity (entity_type, entity_id),
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES staff_users (user_id)
);

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id INT NOT NULL,
    medication_alerts TINYINT(1) NOT NULL DEFAULT 1,
    task_alerts TINYINT(1) NOT NULL DEFAULT 1,
    shift_alerts TINYINT(1) NOT NULL DEFAULT 1,
    daily_summary TINYINT(1) NOT NULL DEFAULT 1,
    push_subscription_json TEXT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    CONSTRAINT fk_notification_user FOREIGN KEY (user_id) REFERENCES staff_users (user_id)
);
