CREATE TABLE agent_drafts (
    update_id bigint PRIMARY KEY REFERENCES inbound_updates(update_id),
    family_id bigint NOT NULL REFERENCES families(id),
    child_id bigint NOT NULL,
    telegram_user_id bigint NOT NULL,
    events jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','cancelled')),
    FOREIGN KEY (family_id,child_id) REFERENCES children(family_id,id),
    FOREIGN KEY (family_id,telegram_user_id) REFERENCES family_members(family_id,telegram_user_id)
);
