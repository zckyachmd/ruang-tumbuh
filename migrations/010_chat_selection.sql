CREATE TABLE chat_selections (
    telegram_user_id bigint PRIMARY KEY,
    family_id bigint NOT NULL,
    child_id bigint NOT NULL,
    selected_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (family_id, telegram_user_id) REFERENCES family_members(family_id, telegram_user_id) ON DELETE CASCADE,
    FOREIGN KEY (family_id, child_id) REFERENCES children(family_id, id) ON DELETE CASCADE
);
