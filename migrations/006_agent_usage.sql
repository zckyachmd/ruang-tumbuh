CREATE TABLE agent_usage (
    update_id bigint PRIMARY KEY REFERENCES inbound_updates(update_id),
    family_id bigint NOT NULL REFERENCES families(id),
    model text NOT NULL,
    input_tokens bigint NOT NULL CHECK (input_tokens >= 0),
    output_tokens bigint NOT NULL CHECK (output_tokens >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
