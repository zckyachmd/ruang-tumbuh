CREATE TABLE families (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL CHECK (length(trim(name)) > 0),
    timezone text NOT NULL DEFAULT 'Asia/Jakarta',
    deleted_at timestamptz
);

CREATE TABLE family_members (
    family_id bigint NOT NULL REFERENCES families(id),
    telegram_user_id bigint NOT NULL,
    role text NOT NULL CHECK (role IN ('owner', 'member')),
    revoked_at timestamptz,
    PRIMARY KEY (family_id, telegram_user_id)
);

CREATE TABLE children (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    family_id bigint NOT NULL REFERENCES families(id),
    nickname text NOT NULL CHECK (length(trim(nickname)) > 0),
    birth_date date,
    sex text CHECK (sex IN ('male', 'female')),
    premature_notes text,
    UNIQUE (family_id, id)
);

CREATE TABLE invitations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    family_id bigint NOT NULL REFERENCES families(id),
    token_hash bytea NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    used_by bigint,
    CHECK ((used_at IS NULL) = (used_by IS NULL))
);

CREATE TABLE events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    family_id bigint NOT NULL,
    child_id bigint NOT NULL,
    kind text NOT NULL CHECK (kind IN ('feeding', 'diaper', 'sleep', 'growth', 'note')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    deleted_at timestamptz,
    FOREIGN KEY (family_id, child_id) REFERENCES children(family_id, id),
    FOREIGN KEY (family_id, created_by) REFERENCES family_members(family_id, telegram_user_id)
);
CREATE INDEX events_timeline ON events (family_id, child_id, occurred_at DESC, id DESC) WHERE deleted_at IS NULL;

CREATE TABLE inbound_updates (
    update_id bigint PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);
CREATE TABLE actions (
    update_id bigint NOT NULL REFERENCES inbound_updates(update_id),
    action_key text NOT NULL,
    request_hash bytea NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (update_id, action_key)
);

CREATE TABLE sessions (
    token_hash bytea PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX sessions_expiry ON sessions (expires_at);

CREATE TABLE api_actions (
    telegram_user_id bigint NOT NULL,
    action_key text NOT NULL,
    request_hash bytea NOT NULL,
    result jsonb,
    PRIMARY KEY (telegram_user_id, action_key)
);

CREATE TABLE notification_preferences (
    family_id bigint NOT NULL,
    telegram_user_id bigint NOT NULL,
    kind text NOT NULL CHECK (kind IN ('checkin', 'daily_summary', 'reminder', 'clarification')),
    enabled boolean NOT NULL DEFAULT false,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(settings) = 'object'),
    PRIMARY KEY (family_id, telegram_user_id, kind),
    FOREIGN KEY (family_id, telegram_user_id) REFERENCES family_members(family_id, telegram_user_id)
);

CREATE TABLE scheduled_occurrences (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    family_id bigint NOT NULL,
    telegram_user_id bigint NOT NULL,
    occurrence_key text NOT NULL,
    due_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > due_at),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'attempted', 'sent', 'failed', 'uncertain', 'cancelled')),
    UNIQUE (family_id, telegram_user_id, occurrence_key),
    FOREIGN KEY (family_id, telegram_user_id) REFERENCES family_members(family_id, telegram_user_id)
);

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    family_id bigint NOT NULL REFERENCES families(id),
    actor_id bigint NOT NULL,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (family_id, actor_id) REFERENCES family_members(family_id, telegram_user_id)
);

