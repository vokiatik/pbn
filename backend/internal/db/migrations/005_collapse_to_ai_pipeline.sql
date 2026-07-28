ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS pipeline_version TEXT NOT NULL DEFAULT 'ai';

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_pipeline_version_check;

UPDATE projects
SET pipeline_version = 'ai'
WHERE pipeline_version IS DISTINCT FROM 'ai';

ALTER TABLE projects
    ALTER COLUMN pipeline_version SET DEFAULT 'ai';

ALTER TABLE projects
    ADD CONSTRAINT projects_pipeline_version_check
    CHECK (pipeline_version IN ('ai'));

ALTER TABLE projects
    DROP COLUMN IF EXISTS v2_settings;

ALTER TABLE projects
    DROP COLUMN IF EXISTS v3_settings;

ALTER TABLE projects
    DROP COLUMN IF EXISTS v3_revision;
