ALTER TABLE assignments
ADD COLUMN assignment_type VARCHAR(30) NOT NULL DEFAULT 'Automatic',
ADD COLUMN override_reason VARCHAR(200) NULL,
ADD COLUMN finalized_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
ADD UNIQUE KEY uq_assignment_date_dog (assignment_date, dog_id);
