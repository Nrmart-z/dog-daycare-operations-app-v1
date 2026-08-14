ALTER TABLE dogs_info
ADD CONSTRAINT chk_dogs_info_play_group
CHECK (play_group IN ('Big', 'Small', 'Separate'));
