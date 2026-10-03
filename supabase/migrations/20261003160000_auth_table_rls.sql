-- Own-auth tables were created after the migration that enabled RLS on the
-- tenant tables, so they were the only live tables left without it (review
-- P1 — authentication table exposure). Same no-policy posture as the rest of
-- the schema: the Data API roles get no direct access; only the server path
-- (service role) reads or writes these rows.
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY;
