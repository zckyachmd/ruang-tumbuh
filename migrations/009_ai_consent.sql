CREATE TABLE ai_processing_consents (
    family_id bigint NOT NULL,
    telegram_user_id bigint NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (family_id,telegram_user_id),
    FOREIGN KEY (family_id,telegram_user_id) REFERENCES family_members(family_id,telegram_user_id)
);
