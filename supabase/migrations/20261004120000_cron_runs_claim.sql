-- Atomic daily-schedule claim (review P1 — durable jobs).
--
-- The scheduler used to check a `cron.ran` audit marker and then select /
-- create scans as separate operations: multiple API replicas could pass the
-- check before any writes landed and sweep the same day twice. cron_runs
-- makes the whole sweep one atomic Postgres claim —
-- INSERT ... ON CONFLICT DO UPDATE ... RETURNING hands ownership to exactly
-- one caller per (cron_name, run_day):
--   fresh insert                -> caller owns the run
--   status = 'failed'           -> a retry takes over a failed run
--   running and stale (>30 min) -> takeover after a crashed owner
--   running, fresh              -> another owner is mid-run (denied)
--   completed                   -> never re-run (denied)
CREATE TABLE IF NOT EXISTS cron_runs (
  cron_name   text        NOT NULL,
  run_day     date        NOT NULL,
  claimed_by  text,
  status      text        NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'failed')),
  claimed_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  PRIMARY KEY (cron_name, run_day)
);

-- Same no-policy RLS posture as the tenant tables: the Data API roles get no
-- direct access; only the server path touches these rows.
ALTER TABLE cron_runs ENABLE ROW LEVEL SECURITY;
