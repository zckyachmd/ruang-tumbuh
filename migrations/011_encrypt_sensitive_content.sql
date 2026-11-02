ALTER TABLE families DROP CONSTRAINT families_name_check;
ALTER TABLE children DROP CONSTRAINT children_nickname_check;
ALTER TABLE children DROP CONSTRAINT children_sex_check;
ALTER TABLE children ALTER COLUMN birth_date TYPE text USING birth_date::text;
ALTER TABLE events DROP CONSTRAINT events_payload_check;
ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_settings_check;
ALTER TABLE reminders DROP CONSTRAINT reminders_body_check;
