CREATE TABLE IF NOT EXISTS boarding_reservations (
    reservation_id INT NOT NULL AUTO_INCREMENT,
    dog_id INT NOT NULL,
    arrival_date DATE NOT NULL,
    departure_date DATE NOT NULL,
    pickup_period VARCHAR(10) NOT NULL DEFAULT 'PM',
    room_id INT NOT NULL,
    notes VARCHAR(500) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Planned',
    created_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (reservation_id),
    KEY idx_reservation_arrival (arrival_date, status),
    KEY idx_reservation_departure (departure_date, status),
    CONSTRAINT fk_reservation_dog FOREIGN KEY (dog_id) REFERENCES dogs_info (dog_id),
    CONSTRAINT fk_reservation_room FOREIGN KEY (room_id) REFERENCES rooms (room_id),
    CONSTRAINT fk_reservation_creator FOREIGN KEY (created_by_user_id) REFERENCES staff_users (user_id)
);
