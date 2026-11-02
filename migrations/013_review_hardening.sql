ALTER TABLE chat_outbox ADD COLUMN attempts integer NOT NULL DEFAULT 0;
ALTER TABLE chat_outbox ADD COLUMN next_attempt_at timestamptz;
ALTER TABLE scheduled_occurrences ADD COLUMN attempts integer NOT NULL DEFAULT 0;
CREATE INDEX inbound_user_order ON inbound_updates (telegram_user_id,received_at,update_id)
    WHERE status IN ('pending','processing');

CREATE TABLE conversation_contexts (
    telegram_user_id bigint NOT NULL,
    family_id bigint NOT NULL,
    child_id bigint NOT NULL,
    content text NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (telegram_user_id,family_id,child_id),
    FOREIGN KEY (family_id,telegram_user_id) REFERENCES family_members(family_id,telegram_user_id) ON DELETE CASCADE,
    FOREIGN KEY (family_id,child_id) REFERENCES children(family_id,id) ON DELETE CASCADE
);
CREATE TABLE ai_reservations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    update_id bigint NOT NULL REFERENCES inbound_updates(update_id),
    family_id bigint NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    telegram_user_id bigint NOT NULL,
    reserved_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ai_reservation_day ON ai_reservations (reserved_at,family_id,telegram_user_id);
CREATE TABLE worker_heartbeats (name text PRIMARY KEY, seen_at timestamptz NOT NULL);
