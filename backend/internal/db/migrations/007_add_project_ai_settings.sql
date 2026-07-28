ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS ai_settings JSONB NOT NULL DEFAULT '{}'::jsonb;
