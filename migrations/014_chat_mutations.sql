CREATE TABLE chat_mutations (
    update_id bigint PRIMARY KEY REFERENCES inbound_updates(update_id),
    family_id bigint NOT NULL,
    child_id bigint NOT NULL,
    telegram_user_id bigint NOT NULL,
    content text NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '30 minutes',
    status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','cancelled')),
    FOREIGN KEY(family_id,child_id) REFERENCES children(family_id,id) ON DELETE CASCADE,
    FOREIGN KEY(family_id,telegram_user_id) REFERENCES family_members(family_id,telegram_user_id) ON DELETE CASCADE
);
