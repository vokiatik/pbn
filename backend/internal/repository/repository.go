package repository

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("not found")

type Project struct {
	ID               uuid.UUID       `json:"id"`
	PublicID         string          `json:"public_id"`
	UserID           *uuid.UUID      `json:"user_id,omitempty"`
	Username         string          `json:"username"`
	ClientToken      string          `json:"-"`
	OriginalFilename string          `json:"original_filename"`
	OriginalFilePath string          `json:"original_file_path"`
	PipelineVersion  string          `json:"pipeline_version"`
	AISettings       json.RawMessage `json:"ai_settings"`
	AIQuality        json.RawMessage `json:"ai_quality"`
	PBNOptions       json.RawMessage `json:"pbn_options"`
	SelectedPBN      *string         `json:"selected_pbn_difficulty,omitempty"`
	Status           string          `json:"status"`
	ErrorMessage     *string         `json:"error_message,omitempty"`
	CreatedAt        time.Time       `json:"created_at"`
	UpdatedAt        time.Time       `json:"updated_at"`
	CompletedAt      *time.Time      `json:"completed_at,omitempty"`
	DeletedAt        *time.Time      `json:"deleted_at,omitempty"`
	FilesCount       int             `json:"files_count"`
}

type ProjectFile struct {
	ID        uuid.UUID `json:"id"`
	ProjectID uuid.UUID `json:"project_id"`
	FileType  string    `json:"file_type"`
	Filename  string    `json:"filename"`
	FilePath  string    `json:"file_path"`
	MimeType  string    `json:"mime_type"`
	SizeBytes int64     `json:"size_bytes"`
	CreatedAt time.Time `json:"created_at"`
}

type User struct {
	ID          uuid.UUID `json:"id"`
	Username    string    `json:"username"`
	Email       string    `json:"email"`
	PhoneNumber string    `json:"phone_number"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type ProjectRepository interface {
	CreateProject(ctx context.Context, p Project) error
	GetProjectByPublicID(ctx context.Context, publicID string) (Project, error)
	GetProjectByID(ctx context.Context, id uuid.UUID) (Project, error)
	ListProjects(ctx context.Context, page int, pageSize int) ([]Project, int64, error)
	CountActiveByClientToken(ctx context.Context, clientToken string) (int, error)
	UpdateProjectStatus(ctx context.Context, projectID uuid.UUID, status string, completed bool, errorMessage *string) error
	UpdateProjectAISettings(ctx context.Context, projectID uuid.UUID, settings json.RawMessage) error
	UpdateProjectAIQuality(ctx context.Context, projectID uuid.UUID, quality json.RawMessage) error
	UpdateProjectPBNOptions(ctx context.Context, projectID uuid.UUID, options json.RawMessage) error
	UpdateSelectedPBNDifficulty(ctx context.Context, projectID uuid.UUID, difficulty *string) error
	ReplaceProjectOriginal(ctx context.Context, projectID uuid.UUID, originalFilename string, originalFilePath string, files []ProjectFile) error
	SoftDeleteProject(ctx context.Context, publicID string) error
	ReplaceProjectFiles(ctx context.Context, projectID uuid.UUID, files []ProjectFile) error
	ListProjectFiles(ctx context.Context, projectID uuid.UUID) ([]ProjectFile, error)
	GetProjectFileByID(ctx context.Context, projectID uuid.UUID, fileID uuid.UUID) (ProjectFile, error)
	AttachUser(ctx context.Context, projectID uuid.UUID, userID uuid.UUID) error
}

type UserRepository interface {
	GetUserByEmail(ctx context.Context, email string) (User, error)
	CreateUser(ctx context.Context, user User) (User, error)
}

type PostgresRepository struct {
	pool *pgxpool.Pool
}

func NewPostgresRepository(pool *pgxpool.Pool) *PostgresRepository {
	return &PostgresRepository{pool: pool}
}

func (r *PostgresRepository) CreateProject(ctx context.Context, p Project) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO projects (
			id, public_id, user_id, client_token, original_filename, original_file_path, pipeline_version, status
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
	`, p.ID, p.PublicID, p.UserID, p.ClientToken, p.OriginalFilename, p.OriginalFilePath, p.PipelineVersion, p.Status)
	return err
}

func (r *PostgresRepository) GetProjectByPublicID(ctx context.Context, publicID string) (Project, error) {
	var p Project
	err := r.pool.QueryRow(ctx, `
		SELECT p.id, p.public_id, p.user_id, COALESCE(u.username,''), COALESCE(p.client_token,''), p.original_filename,
			p.original_file_path, p.pipeline_version, p.ai_settings, p.ai_quality, p.pbn_options, p.selected_pbn_difficulty, p.status, p.error_message, p.created_at, p.updated_at, p.completed_at, p.deleted_at,
			(SELECT COUNT(*) FROM project_files pf WHERE pf.project_id = p.id)
		FROM projects p
		LEFT JOIN users u ON u.id = p.user_id
		WHERE p.public_id=$1
	`, publicID).Scan(
		&p.ID, &p.PublicID, &p.UserID, &p.Username, &p.ClientToken, &p.OriginalFilename,
		&p.OriginalFilePath, &p.PipelineVersion, &p.AISettings, &p.AIQuality, &p.PBNOptions, &p.SelectedPBN, &p.Status, &p.ErrorMessage, &p.CreatedAt, &p.UpdatedAt, &p.CompletedAt, &p.DeletedAt,
		&p.FilesCount,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Project{}, ErrNotFound
		}
		return Project{}, err
	}
	return p, nil
}

func (r *PostgresRepository) GetProjectByID(ctx context.Context, id uuid.UUID) (Project, error) {
	var p Project
	err := r.pool.QueryRow(ctx, `
		SELECT p.id, p.public_id, p.user_id, COALESCE(u.username,''), COALESCE(p.client_token,''), p.original_filename,
			p.original_file_path, p.pipeline_version, p.ai_settings, p.ai_quality, p.pbn_options, p.selected_pbn_difficulty, p.status, p.error_message, p.created_at, p.updated_at, p.completed_at, p.deleted_at,
			(SELECT COUNT(*) FROM project_files pf WHERE pf.project_id = p.id)
		FROM projects p
		LEFT JOIN users u ON u.id = p.user_id
		WHERE p.id=$1
	`, id).Scan(
		&p.ID, &p.PublicID, &p.UserID, &p.Username, &p.ClientToken, &p.OriginalFilename,
		&p.OriginalFilePath, &p.PipelineVersion, &p.AISettings, &p.AIQuality, &p.PBNOptions, &p.SelectedPBN, &p.Status, &p.ErrorMessage, &p.CreatedAt, &p.UpdatedAt, &p.CompletedAt, &p.DeletedAt,
		&p.FilesCount,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Project{}, ErrNotFound
		}
		return Project{}, err
	}
	return p, nil
}

func (r *PostgresRepository) ListProjects(ctx context.Context, page int, pageSize int) ([]Project, int64, error) {
	if page < 1 {
		page = 1
	}
	offset := (page - 1) * pageSize

	rows, err := r.pool.Query(ctx, `
		SELECT p.id, p.public_id, p.user_id, COALESCE(u.username,''), COALESCE(p.client_token,''), p.original_filename,
			p.original_file_path, p.pipeline_version, p.ai_settings, p.ai_quality, p.pbn_options, p.selected_pbn_difficulty, p.status, p.error_message, p.created_at, p.updated_at, p.completed_at, p.deleted_at,
			(SELECT COUNT(*) FROM project_files pf WHERE pf.project_id = p.id)
		FROM projects p
		LEFT JOIN users u ON u.id = p.user_id
		WHERE p.deleted_at IS NULL
		ORDER BY p.created_at DESC
		LIMIT $1 OFFSET $2
	`, pageSize, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	projects := make([]Project, 0, pageSize)
	for rows.Next() {
		var p Project
		if err := rows.Scan(
			&p.ID, &p.PublicID, &p.UserID, &p.Username, &p.ClientToken, &p.OriginalFilename,
			&p.OriginalFilePath, &p.PipelineVersion, &p.AISettings, &p.AIQuality, &p.PBNOptions, &p.SelectedPBN, &p.Status, &p.ErrorMessage, &p.CreatedAt, &p.UpdatedAt, &p.CompletedAt, &p.DeletedAt,
			&p.FilesCount,
		); err != nil {
			return nil, 0, err
		}
		projects = append(projects, p)
	}

	var total int64
	if err := r.pool.QueryRow(ctx, "SELECT COUNT(*) FROM projects WHERE deleted_at IS NULL").Scan(&total); err != nil {
		return nil, 0, err
	}

	return projects, total, nil
}

func (r *PostgresRepository) CountActiveByClientToken(ctx context.Context, clientToken string) (int, error) {
	var count int
	err := r.pool.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM projects
		WHERE deleted_at IS NULL
			AND client_token = $1
			AND (
				status IN ('ai_queued','ai_processing','ai_image_queued','ai_image_processing','pbn_queued','pbn_processing','pbn_options_queued','pbn_options_processing','pbn_selection_queued','pbn_selection_processing')
			)
	`, clientToken).Scan(&count)
	return count, err
}

func (r *PostgresRepository) UpdateProjectStatus(ctx context.Context, projectID uuid.UUID, status string, completed bool, errorMessage *string) error {
	if errorMessage != nil {
		return r.updateProjectStatusAndError(ctx, projectID, status, completed, *errorMessage)
	}

	if completed {
		_, err := r.pool.Exec(ctx, `
			UPDATE projects
			SET status=$2, completed_at=NOW(), updated_at=NOW()
			WHERE id=$1
		`, projectID, status)
		return err
	}
	_, err := r.pool.Exec(ctx, `
		UPDATE projects
		SET status=$2, completed_at=NULL, updated_at=NOW()
		WHERE id=$1
	`, projectID, status)
	return err
}

func (r *PostgresRepository) UpdateProjectAISettings(ctx context.Context, projectID uuid.UUID, settings json.RawMessage) error {
	cmd, err := r.pool.Exec(ctx, `
		UPDATE projects
		SET ai_settings=$2, updated_at=NOW()
		WHERE id=$1 AND deleted_at IS NULL
	`, projectID, settings)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *PostgresRepository) UpdateProjectAIQuality(ctx context.Context, projectID uuid.UUID, quality json.RawMessage) error {
	cmd, err := r.pool.Exec(ctx, `
		UPDATE projects
		SET ai_quality=$2, updated_at=NOW()
		WHERE id=$1 AND deleted_at IS NULL
	`, projectID, quality)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *PostgresRepository) UpdateProjectPBNOptions(ctx context.Context, projectID uuid.UUID, options json.RawMessage) error {
	cmd, err := r.pool.Exec(ctx, `
		UPDATE projects
		SET pbn_options=$2, selected_pbn_difficulty=NULL, updated_at=NOW()
		WHERE id=$1 AND deleted_at IS NULL
	`, projectID, options)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *PostgresRepository) UpdateSelectedPBNDifficulty(ctx context.Context, projectID uuid.UUID, difficulty *string) error {
	cmd, err := r.pool.Exec(ctx, `
		UPDATE projects SET selected_pbn_difficulty=$2, updated_at=NOW()
		WHERE id=$1 AND deleted_at IS NULL
	`, projectID, difficulty)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *PostgresRepository) updateProjectStatusAndError(ctx context.Context, projectID uuid.UUID, status string, completed bool, errorMessage string) error {
	if completed {
		_, err := r.pool.Exec(ctx, `
			UPDATE projects
			SET status=$2, error_message=NULLIF($3, ''), completed_at=NOW(), updated_at=NOW()
			WHERE id=$1
		`, projectID, status, errorMessage)
		return err
	}
	_, err := r.pool.Exec(ctx, `
		UPDATE projects
		SET status=$2, error_message=NULLIF($3, ''), completed_at=NULL, updated_at=NOW()
		WHERE id=$1
	`, projectID, status, errorMessage)
	return err
}

func (r *PostgresRepository) ReplaceProjectOriginal(ctx context.Context, projectID uuid.UUID, originalFilename string, originalFilePath string, files []ProjectFile) error {
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	cmd, err := tx.Exec(ctx, `
		UPDATE projects
		SET original_filename=$2,
			original_file_path=$3,
			ai_settings='{}'::jsonb,
			ai_quality='{}'::jsonb,
			pbn_options='[]'::jsonb,
			selected_pbn_difficulty=NULL,
			status='uploaded',
			error_message=NULL,
			completed_at=NULL,
			updated_at=NOW()
		WHERE id=$1 AND deleted_at IS NULL
	`, projectID, originalFilename, originalFilePath)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}

	if _, err := tx.Exec(ctx, "DELETE FROM project_files WHERE project_id=$1", projectID); err != nil {
		return err
	}

	for _, f := range files {
		if f.ID == uuid.Nil {
			f.ID = uuid.New()
		}
		_, err := tx.Exec(ctx, `
			INSERT INTO project_files (
				id, project_id, file_type, filename, file_path, mime_type, size_bytes
			) VALUES ($1,$2,$3,$4,$5,$6,$7)
		`, f.ID, projectID, f.FileType, f.Filename, f.FilePath, f.MimeType, f.SizeBytes)
		if err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}

func (r *PostgresRepository) SoftDeleteProject(ctx context.Context, publicID string) error {
	cmd, err := r.pool.Exec(ctx, `
		UPDATE projects
		SET status='deleted', deleted_at=NOW(), updated_at=NOW()
		WHERE public_id=$1 AND deleted_at IS NULL
	`, publicID)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (r *PostgresRepository) ReplaceProjectFiles(ctx context.Context, projectID uuid.UUID, files []ProjectFile) error {
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, "DELETE FROM project_files WHERE project_id=$1", projectID); err != nil {
		return err
	}

	for _, f := range files {
		if f.ID == uuid.Nil {
			f.ID = uuid.New()
		}
		_, err := tx.Exec(ctx, `
			INSERT INTO project_files (
				id, project_id, file_type, filename, file_path, mime_type, size_bytes
			) VALUES ($1,$2,$3,$4,$5,$6,$7)
		`, f.ID, projectID, f.FileType, f.Filename, f.FilePath, f.MimeType, f.SizeBytes)
		if err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}

func (r *PostgresRepository) ListProjectFiles(ctx context.Context, projectID uuid.UUID) ([]ProjectFile, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, project_id, file_type, filename, file_path, mime_type, size_bytes, created_at
		FROM project_files WHERE project_id=$1 ORDER BY created_at ASC
	`, projectID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	files := make([]ProjectFile, 0)
	for rows.Next() {
		var f ProjectFile
		if err := rows.Scan(&f.ID, &f.ProjectID, &f.FileType, &f.Filename, &f.FilePath, &f.MimeType, &f.SizeBytes, &f.CreatedAt); err != nil {
			return nil, err
		}
		files = append(files, f)
	}
	return files, nil
}

func (r *PostgresRepository) GetProjectFileByID(ctx context.Context, projectID uuid.UUID, fileID uuid.UUID) (ProjectFile, error) {
	var f ProjectFile
	err := r.pool.QueryRow(ctx, `
		SELECT id, project_id, file_type, filename, file_path, mime_type, size_bytes, created_at
		FROM project_files WHERE project_id=$1 AND id=$2
	`, projectID, fileID).Scan(&f.ID, &f.ProjectID, &f.FileType, &f.Filename, &f.FilePath, &f.MimeType, &f.SizeBytes, &f.CreatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ProjectFile{}, ErrNotFound
		}
		return ProjectFile{}, err
	}
	return f, nil
}

func (r *PostgresRepository) AttachUser(ctx context.Context, projectID uuid.UUID, userID uuid.UUID) error {
	_, err := r.pool.Exec(ctx, `
		UPDATE projects
		SET user_id=$2, updated_at=NOW()
		WHERE id=$1
	`, projectID, userID)
	return err
}

func (r *PostgresRepository) GetUserByEmail(ctx context.Context, email string) (User, error) {
	var u User
	err := r.pool.QueryRow(ctx, `
		SELECT id, COALESCE(username,''), email, COALESCE(phone_number,''), created_at, updated_at
		FROM users WHERE LOWER(email)=LOWER($1)
	`, email).Scan(&u.ID, &u.Username, &u.Email, &u.PhoneNumber, &u.CreatedAt, &u.UpdatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	return u, nil
}

func (r *PostgresRepository) CreateUser(ctx context.Context, user User) (User, error) {
	var out User
	err := r.pool.QueryRow(ctx, `
		INSERT INTO users (id, username, email, phone_number)
		VALUES ($1,$2,$3,$4)
		RETURNING id, COALESCE(username,''), email, COALESCE(phone_number,''), created_at, updated_at
	`, uuid.New(), user.Username, user.Email, user.PhoneNumber).Scan(
		&out.ID, &out.Username, &out.Email, &out.PhoneNumber, &out.CreatedAt, &out.UpdatedAt,
	)
	return out, err
}
