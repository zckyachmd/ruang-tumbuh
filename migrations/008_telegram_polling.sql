CREATE TABLE telegram_poll_cursor (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    next_offset bigint NOT NULL CHECK (next_offset >= 0)
);
