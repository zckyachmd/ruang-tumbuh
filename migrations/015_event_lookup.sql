ALTER TABLE events ADD COLUMN lookup_token bytea;
CREATE INDEX events_lookup ON events(family_id,child_id,lookup_token,occurred_at DESC,id DESC)
    WHERE deleted_at IS NULL;
