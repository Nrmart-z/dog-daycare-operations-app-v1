CREATE TABLE IF NOT EXISTS boarding_care_profiles (
    boarding_stay_id INT NOT NULL,
    breakfast_required TINYINT(1) NOT NULL DEFAULT 0,
    lunch_required TINYINT(1) NOT NULL DEFAULT 0,
    dinner_required TINYINT(1) NOT NULL DEFAULT 0,
    breakfast_med_required TINYINT(1) NOT NULL DEFAULT 0,
    lunch_med_required TINYINT(1) NOT NULL DEFAULT 0,
    dinner_med_required TINYINT(1) NOT NULL DEFAULT 0,
    feeding_tricks VARCHAR(500) NULL,
    medication_tips VARCHAR(500) NULL,
    allergy_status VARCHAR(20) NOT NULL DEFAULT 'Not recorded',
    allergy_details VARCHAR(500) NULL,
    food_label VARCHAR(200) NULL,
    different_food_alert TINYINT(1) NOT NULL DEFAULT 0,
    feeding_setup VARCHAR(30) NOT NULL DEFAULT 'Normal',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (boarding_stay_id),
    CONSTRAINT fk_boarding_care_profile_stay FOREIGN KEY (boarding_stay_id)
        REFERENCES boarding_stays (boarding_stay_id)
);

CREATE TABLE IF NOT EXISTS boarding_feeding_records (
    feeding_record_id INT NOT NULL AUTO_INCREMENT,
    boarding_stay_id INT NOT NULL,
    feeding_date DATE NOT NULL,
    meal VARCHAR(20) NOT NULL,
    placed_by VARCHAR(10) NULL,
    placed_at DATETIME NULL,
    picked_up_by VARCHAR(10) NULL,
    picked_up_at DATETIME NULL,
    appetite VARCHAR(10) NULL,
    meal_note VARCHAR(500) NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (feeding_record_id),
    UNIQUE KEY uq_boarding_feeding (boarding_stay_id, feeding_date, meal),
    CONSTRAINT fk_boarding_feeding_stay FOREIGN KEY (boarding_stay_id)
        REFERENCES boarding_stays (boarding_stay_id)
);

CREATE TABLE IF NOT EXISTS boarding_medication_checks (
    medication_check_id INT NOT NULL AUTO_INCREMENT,
    boarding_stay_id INT NOT NULL,
    check_date DATE NOT NULL,
    meal VARCHAR(20) NOT NULL,
    result VARCHAR(20) NOT NULL,
    employee_initials VARCHAR(10) NOT NULL,
    completed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    administration_note VARCHAR(500) NULL,
    PRIMARY KEY (medication_check_id),
    UNIQUE KEY uq_boarding_medication (boarding_stay_id, check_date, meal),
    CONSTRAINT fk_boarding_medication_stay FOREIGN KEY (boarding_stay_id)
        REFERENCES boarding_stays (boarding_stay_id)
);

CREATE TABLE IF NOT EXISTS boarding_care_notes (
    boarding_note_id INT NOT NULL AUTO_INCREMENT,
    boarding_stay_id INT NOT NULL,
    employee_initials VARCHAR(10) NOT NULL,
    note_text VARCHAR(1000) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (boarding_note_id),
    KEY idx_boarding_note_stay (boarding_stay_id, created_at),
    CONSTRAINT fk_boarding_note_stay FOREIGN KEY (boarding_stay_id)
        REFERENCES boarding_stays (boarding_stay_id)
);
