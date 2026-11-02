"""Remove expired transient content without forgetting Telegram update IDs."""


def cleanup(store, chat_content_retention_days=7):
    if type(chat_content_retention_days) is not int or not 1 <= chat_content_retention_days <= 30:
        raise ValueError('CHAT_CONTENT_RETENTION_DAYS must be between 1 and 30')
    with store.connect() as conn:
        conn.execute('DELETE FROM sessions WHERE expires_at < now()')
        conn.execute('DELETE FROM conversation_contexts WHERE expires_at < now()')
        conn.execute('DELETE FROM chat_mutations WHERE expires_at < now()')
        conn.execute("DELETE FROM ai_reservations WHERE reserved_at < now()-interval '2 days'")
        conn.execute('DELETE FROM family_deletion_requests WHERE expires_at < now()')
        conn.execute("DELETE FROM family_deletion_receipts WHERE deleted_at < now() - interval '90 days'")
        conn.execute('DELETE FROM chat_drafts WHERE expires_at < now()')
        conn.execute('DELETE FROM agent_drafts WHERE expires_at < now()')
        conn.execute("""UPDATE actions a SET result='{}'::jsonb FROM inbound_updates u
            WHERE a.update_id=u.update_id AND a.action_key='create_invitation'
            AND u.received_at < now()-interval '2 days' AND a.result <> '{}'::jsonb""")
        conn.execute("""UPDATE chat_outbox o SET status='failed',finished_at=now() FROM actions a
            JOIN inbound_updates u ON u.update_id=a.update_id
            WHERE o.update_id=a.update_id AND a.action_key='create_invitation'
            AND u.received_at < now()-interval '2 days' AND o.status='pending'""")
        conn.execute("""UPDATE chat_outbox o SET body='',reply_markup='' FROM actions a
            JOIN inbound_updates u ON u.update_id=a.update_id
            WHERE o.update_id=a.update_id AND a.action_key='create_invitation'
            AND u.received_at < now()-interval '2 days' AND o.status IN ('sent','simulated','failed','uncertain') AND o.body<>''""")
        conn.execute("""UPDATE inbound_updates SET status='failed',last_error='expired',lease_until=NULL,lease_token=NULL
            WHERE received_at < now() - (%s * interval '1 day')
            AND (status='pending' OR (status='processing' AND lease_until < now()))""", (chat_content_retention_days,))
        conn.execute("""UPDATE chat_outbox o SET status='failed',finished_at=now() FROM inbound_updates u
            WHERE o.update_id=u.update_id AND o.status='pending' AND u.received_at < now() - (%s * interval '1 day')""", (chat_content_retention_days,))
        conn.execute("UPDATE chat_outbox SET status='uncertain',finished_at=now() WHERE status='attempted' AND attempted_at < now() - interval '2 minutes'")
        conn.execute("""UPDATE chat_outbox o SET body='',reply_markup='' FROM inbound_updates u
            WHERE o.update_id=u.update_id AND u.received_at < now() - (%s * interval '1 day')
            AND o.status IN ('sent','simulated','failed','uncertain') AND o.body <> ''""", (chat_content_retention_days,))
        conn.execute("""UPDATE inbound_updates u SET payload='{}'::jsonb
            WHERE u.received_at < now() - (%s * interval '1 day') AND u.status IN ('completed','failed')
            AND NOT EXISTS (SELECT 1 FROM chat_outbox o WHERE o.update_id=u.update_id AND o.status IN ('pending','attempted'))
            AND u.payload <> '{}'::jsonb""", (chat_content_retention_days,))

