-- Kennels 52 and 53 can accommodate sibling pairs through Big + Big.
-- "Large" is the maximum supported shared capacity; smaller pairs remain valid.
UPDATE rooms
SET sibling_capacity = 'Large'
WHERE room_number IN ('52', '53')
  AND room_type = 'Kennel';
