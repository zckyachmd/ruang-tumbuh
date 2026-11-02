CREATE TABLE reminders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    family_id bigint NOT NULL,
    telegram_user_id bigint NOT NULL,
    body text NOT NULL CHECK (length(trim(body)) BETWEEN 1 AND 500),
    due_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > due_at),
    bypass_quiet_hours boolean NOT NULL DEFAULT false,
    cancelled_at timestamptz,
    FOREIGN KEY (family_id,telegram_user_id) REFERENCES family_members(family_id,telegram_user_id),
    UNIQUE (family_id,id)
);
ALTER TABLE scheduled_occurrences ADD COLUMN reminder_id bigint;
ALTER TABLE scheduled_occurrences ADD COLUMN child_id bigint;
ALTER TABLE scheduled_occurrences ADD COLUMN reschedule_allowed boolean NOT NULL DEFAULT false;
ALTER TABLE scheduled_occurrences ADD FOREIGN KEY (family_id,reminder_id) REFERENCES reminders(family_id,id);
ALTER TABLE scheduled_occurrences ADD FOREIGN KEY (family_id,child_id) REFERENCES children(family_id,id);
