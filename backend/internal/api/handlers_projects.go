package api

import (
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"pbn/backend/internal/repository"
	"pbn/backend/internal/service"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (s *Server) handleCreateProject(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(25 << 20); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid multipart form"})
		return
	}

	file, fh, err := r.FormFile("file")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "file is required"})
		return
	}
	defer file.Close()

	if err := validateImageFile(fh); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}

	clientToken := strings.TrimSpace(r.Header.Get("X-Client-Token"))
	if clientToken == "" {
		clientToken = "anonymous"
	}

	activeCount, err := s.repo.CountActiveByClientToken(r.Context(), clientToken)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to evaluate active projects"})
		return
	}
	if activeCount >= s.cfg.MaxActivePerUser {
		writeJSON(w, http.StatusTooManyRequests, map[string]string{"error": "you already have 2 active projects in queue/processing"})
		return
	}

	projectID := uuid.New()
	publicID, err := service.NewPublicID(s.cfg.PublicIDLength)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to create project id"})
		return
	}

	projectRoot := filepath.Join(s.cfg.StorageRoot, "projects", publicID)
	originalDir := filepath.Join(projectRoot, "original")
	generatedDir := filepath.Join(projectRoot, "generated")
	if err := os.MkdirAll(originalDir, 0o755); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to create storage"})
		return
	}
	if err := os.MkdirAll(generatedDir, 0o755); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to create storage"})
		return
	}

	uploadedName := sanitizeFilename(fh.Filename)
	ext := strings.ToLower(filepath.Ext(uploadedName))
	name := "original" + ext
	originalPath := filepath.Join(originalDir, name)

	if err := saveUploadedFile(originalPath, file); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to save upload"})
		return
	}

	project := repository.Project{
		ID:               projectID,
		PublicID:         publicID,
		ClientToken:      clientToken,
		OriginalFilename: name,
		OriginalFilePath: originalPath,
		Status:           "uploaded",
	}
	if err := s.repo.CreateProject(r.Context(), project); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to create project"})
		return
	}

	originalFile := buildOriginalProjectFile(project)
	originalFile.SizeBytes = fh.Size

	if err := s.repo.ReplaceProjectFiles(r.Context(), projectID, []repository.ProjectFile{originalFile}); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to register uploaded file"})
		return
	}

	if isHEICFile(name) {
		payload := map[string]any{
			"type":          "generate_upload_preview",
			"project_id":    project.ID.String(),
			"public_id":     publicID,
			"project_root":  projectRoot,
			"input_path":    originalPath,
			"created_at":    time.Now().UTC().Format(time.RFC3339),
			"retry_count":   0,
			"max_retries":   2,
			"callback_base": fmt.Sprintf("http://backend:%s/api/internal", s.cfg.HTTPPort),
		}

		if err := s.queue.Enqueue(r.Context(), payload); err != nil {
			s.logger.Warn("failed to enqueue upload preview generation", "project_id", project.ID, "public_id", publicID, "error", err)
		}
	}

	_ = s.events.Publish(r.Context(), map[string]any{
		"type":       "status_changed",
		"project_id": publicID,
		"status":     "uploaded",
	})

	writeJSON(w, http.StatusCreated, map[string]any{
		"project_id": publicID,
		"status":     "uploaded",
	})
}

func (s *Server) handleListProjects(w http.ResponseWriter, r *http.Request) {
	page := intParam(r.URL.Query().Get("page"), 1)
	pageSize := intParam(r.URL.Query().Get("page_size"), 10)
	if pageSize > 100 {
		pageSize = 100
	}

	items, total, err := s.repo.ListProjects(r.Context(), page, pageSize)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to list projects"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"items":       items,
		"total":       total,
		"page":        page,
		"page_size":   pageSize,
		"total_pages": (total + int64(pageSize) - 1) / int64(pageSize),
	})
}

func (s *Server) handleGetProject(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")
	project, err := s.repo.GetProjectByPublicID(r.Context(), publicID)
	if err != nil {
		status := http.StatusInternalServerError
		if errors.Is(err, repository.ErrNotFound) {
			status = http.StatusNotFound
		}
		writeJSON(w, status, map[string]string{"error": "project not found"})
		return
	}

	files, err := s.repo.ListProjectFiles(r.Context(), project.ID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to list files"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"project": project,
		"files":   files,
	})
}

func (s *Server) handleDeleteProject(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")
	if err := s.repo.SoftDeleteProject(r.Context(), publicID); err != nil {
		status := http.StatusInternalServerError
		if errors.Is(err, repository.ErrNotFound) {
			status = http.StatusNotFound
		}
		writeJSON(w, status, map[string]string{"error": "project not found"})
		return
	}

	_ = s.events.Publish(r.Context(), map[string]any{
		"type":       "status_changed",
		"project_id": publicID,
		"status":     "deleted",
	})

	writeJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}
