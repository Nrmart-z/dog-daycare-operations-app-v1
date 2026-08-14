ALTER TABLE staff_users ADD COLUMN first_name VARCHAR(60) NOT NULL DEFAULT '' AFTER username;
ALTER TABLE staff_users ADD COLUMN last_name VARCHAR(60) NOT NULL DEFAULT '' AFTER first_name;

UPDATE staff_users
SET first_name = CASE
        WHEN LOCATE(' ', TRIM(display_name)) > 0
            THEN SUBSTRING_INDEX(TRIM(display_name), ' ', 1)
        ELSE TRIM(display_name)
    END,
    last_name = CASE
        WHEN LOCATE(' ', TRIM(display_name)) > 0
            THEN SUBSTRING(TRIM(display_name), LOCATE(' ', TRIM(display_name)) + 1)
        ELSE ''
    END
WHERE first_name = '' AND last_name = '';
