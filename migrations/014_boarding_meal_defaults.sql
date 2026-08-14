ALTER TABLE boarding_care_profiles
    MODIFY breakfast_required TINYINT(1) NOT NULL DEFAULT 1,
    MODIFY dinner_required TINYINT(1) NOT NULL DEFAULT 1;

UPDATE boarding_care_profiles
SET breakfast_required = 1,
    dinner_required = 1;
