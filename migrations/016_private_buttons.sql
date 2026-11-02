ALTER TABLE chat_outbox ADD COLUMN reply_markup text NOT NULL DEFAULT '';
ALTER TABLE chat_outbox ADD COLUMN authorization_families jsonb NOT NULL DEFAULT '[]'::jsonb;
