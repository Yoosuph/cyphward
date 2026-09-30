-- Convert stored scores from the 0-1000 scale to the 0-100 scale.
-- Only touches rows still on the old scale (score > 100).

UPDATE scans
SET score = ROUND(score / 10.0)
WHERE score > 100;

UPDATE score_snapshots
SET score = ROUND(score / 10.0),
    subscores = (
      SELECT jsonb_agg(
        CASE
          WHEN elem ? 'score' AND elem->>'score' IS NOT NULL
          THEN elem || jsonb_build_object(
            'score', ROUND((elem->>'score')::numeric / 10.0),
            'max', CASE WHEN (elem->>'max')::numeric > 100
                        THEN ROUND((elem->>'max')::numeric / 10.0)
                        ELSE (elem->>'max')::numeric END
          )
          WHEN elem ? 'tls' THEN
            -- legacy flat subscores object keys (not array): handled below differently
            elem
          ELSE elem
        END
      )
      FROM jsonb_array_elements(COALESCE(subscores, '[]'::jsonb)) AS elem
    )
WHERE score > 100
  AND jsonb_typeof(subscores) = 'array';

-- Legacy flat-object subscores: {"tls": 520, "dns": 710, ...}
UPDATE score_snapshots
SET subscores = (
  SELECT jsonb_object_agg(
    key,
    CASE WHEN value::numeric > 100 THEN ROUND(value::numeric / 10.0) ELSE value::numeric END
  )
  FROM jsonb_each_text(subscores)
)
WHERE score > 100
  AND jsonb_typeof(subscores) = 'object';

-- stage_progress.scoring.score inside scans
UPDATE scans
SET stage_progress = jsonb_set(
  stage_progress,
  '{scoring,score}',
  to_jsonb(ROUND((stage_progress->'scoring'->>'score')::numeric / 10.0))
)
WHERE stage_progress ? 'scoring'
  AND stage_progress->'scoring' ? 'score'
  AND (stage_progress->'scoring'->>'score')::numeric > 100;

-- Schema default for score_snapshots.max_score-style columns if present
-- (init migration defaults; only alter if the column exists)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'score_snapshots' AND column_name = 'max_score'
  ) THEN
    ALTER TABLE score_snapshots ALTER COLUMN max_score SET DEFAULT 100;
    UPDATE score_snapshots SET max_score = 100 WHERE max_score > 100;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'scans' AND column_name = 'max_score'
  ) THEN
    ALTER TABLE scans ALTER COLUMN max_score SET DEFAULT 100;
    UPDATE scans SET max_score = 100 WHERE max_score > 100;
  END IF;
END $$;
