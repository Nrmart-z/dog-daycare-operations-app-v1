CREATE TABLE boarding_stays (
    boarding_stay_id INT NOT NULL AUTO_INCREMENT,
    dog_id INT NOT NULL,
    check_in_datetime DATETIME NOT NULL,
    planned_checkout_datetime DATETIME NOT NULL,
    actual_checkout_datetime DATETIME NULL,
    assigned_room_id INT NOT NULL,
    stay_status VARCHAR(20) NOT NULL DEFAULT 'Checked In',
    notes VARCHAR(200) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (boarding_stay_id),
    KEY idx_boarding_stay_dates (
        check_in_datetime,
        planned_checkout_datetime,
        stay_status
    ),
    CONSTRAINT fk_boarding_stay_dog
        FOREIGN KEY (dog_id) REFERENCES dogs_info (dog_id),
    CONSTRAINT fk_boarding_stay_room
        FOREIGN KEY (assigned_room_id) REFERENCES rooms (room_id)
);

ALTER TABLE daily_attendance
ADD COLUMN boarding_stay_id INT NULL,
ADD KEY idx_daily_attendance_boarding_stay (boarding_stay_id),
ADD CONSTRAINT fk_daily_attendance_boarding_stay
    FOREIGN KEY (boarding_stay_id)
    REFERENCES boarding_stays (boarding_stay_id);
