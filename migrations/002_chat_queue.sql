ALTER TABLE inbound_updates ADD COLUMN attempts integer NOT NULL DEFAULT 0;
ALTER TABLE inbound_updates ADD COLUMN lease_until timestamptz;
ALTER TABLE inbound_updates ADD COLUMN lease_token text;
ALTER TABLE inbound_updates ADD COLUMN last_error text;
CREATE INDEX inbound_pending ON inbound_updates (received_at) WHERE status IN ('pending','processing');

CREATE TABLE chat_drafts (
    update_id bigint PRIMARY KEY REFERENCES inbound_updates(update_id),
    telegram_user_id bigint NOT NULL,
    text text NOT NULL,
    expires_at timestamptz NOT NULL
);

CREATE TABLE chat_outbox (
    update_id bigint PRIMARY KEY REFERENCES inbound_updates(update_id),
    recipient_id bigint NOT NULL,
    family_id bigint REFERENCES families(id),
    body text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','attempted','sent','simulated','failed','uncertain')),
    attempted_at timestamptz,
    finished_at timestamptz
);
