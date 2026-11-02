ALTER TABLE scheduled_occurrences ADD COLUMN kind text NOT NULL DEFAULT 'checkin';
ALTER TABLE scheduled_occurrences ADD COLUMN local_date date;
ALTER TABLE scheduled_occurrences ADD COLUMN attempted_at timestamptz;
ALTER TABLE scheduled_occurrences ADD COLUMN finished_at timestamptz;
ALTER TABLE scheduled_occurrences ADD COLUMN next_attempt_at timestamptz;
ALTER TABLE scheduled_occurrences DROP CONSTRAINT scheduled_occurrences_status_check;
ALTER TABLE scheduled_occurrences ADD CONSTRAINT scheduled_occurrences_status_check CHECK (status IN ('pending','claimed','attempted','sent','simulated','failed','uncertain','cancelled'));
CREATE INDEX scheduled_due ON scheduled_occurrences (due_at) WHERE status = 'pending';

CREATE TABLE checkin_answers (
    family_id bigint NOT NULL REFERENCES families(id),
    local_date date NOT NULL,
    answered_by bigint NOT NULL,
    answered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (family_id, local_date),
    FOREIGN KEY (family_id, answered_by) REFERENCES family_members(family_id, telegram_user_id)
);
