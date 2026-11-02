ALTER TABLE inbound_updates ADD COLUMN family_id bigint REFERENCES families(id);
ALTER TABLE api_actions ADD COLUMN family_id bigint REFERENCES families(id);

CREATE TABLE family_deletion_requests (
    token_hash bytea PRIMARY KEY,
    family_id bigint NOT NULL REFERENCES families(id),
    actor_id bigint NOT NULL,
    expires_at timestamptz NOT NULL,
    FOREIGN KEY (family_id,actor_id) REFERENCES family_members(family_id,telegram_user_id)
);

CREATE TABLE family_deletion_receipts (
    family_id bigint NOT NULL,
    actor_id bigint NOT NULL,
    token_hash bytea NOT NULL,
    deleted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (family_id,actor_id,token_hash)
);
