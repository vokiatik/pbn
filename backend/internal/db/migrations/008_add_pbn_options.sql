ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS pbn_options JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS selected_pbn_difficulty TEXT NULL;

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_selected_pbn_difficulty_check;

ALTER TABLE projects
    ADD CONSTRAINT projects_selected_pbn_difficulty_check
    CHECK (selected_pbn_difficulty IS NULL OR selected_pbn_difficulty IN ('easy', 'medium', 'hard'));
