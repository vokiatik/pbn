package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"

	"pbn/backend/internal/repository"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (s *Server) handlePreviewFile(w http.ResponseWriter, r *http.Request) {
	s.serveFile(w, r, true)
}

func (s *Server) handleDownloadFile(w http.ResponseWriter, r *http.Request) {
	s.serveFile(w, r, false)
}

func (s *Server) serveFile(w http.ResponseWriter, r *http.Request, inline bool) {
	publicID := chi.URLParam(r, "publicID")
	fileID := chi.URLParam(r, "fileID")

	pid, err := uuid.Parse(fileID)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid file id"})
		return
	}

	project, err := s.repo.GetProjectByPublicID(r.Context(), publicID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "project not found"})
		return
	}

	fileRec, err := s.repo.GetProjectFileByID(r.Context(), project.ID, pid)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "file not found"})
		return
	}

	disp := "attachment"
	if inline {
		disp = "inline"
		requireInlineNoCacheHeaders(w)
	}

	w.Header().Set("Content-Type", fileRec.MimeType)
	w.Header().Set("Content-Disposition", fmt.Sprintf("%s; filename=%q", disp, fileRec.Filename))
	http.ServeFile(w, r, fileRec.FilePath)
}

func (s *Server) handleInternalFilesUpdate(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	projectID, err := uuid.Parse(id)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid project id"})
		return
	}

	var req internalFilesUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid payload"})
		return
	}

	project, err := s.repo.GetProjectByID(r.Context(), projectID)
	if err != nil {
		status := http.StatusInternalServerError
		if errors.Is(err, repository.ErrNotFound) {
			status = http.StatusNotFound
		}
		writeJSON(w, status, map[string]string{"error": "project not found"})
		return
	}

	existing, _ := s.repo.ListProjectFiles(r.Context(), projectID)

	files := make([]repository.ProjectFile, 0, len(existing)+len(req.Files)+1)
	files = append(files, buildOriginalProjectFile(project))
	files = append(files, existing...)
	files = append(files, req.Files...)
	files = dedupeProjectFilesByType(files)

	for i := range files {
		files[i].ProjectID = projectID
	}

	if err := s.repo.ReplaceProjectFiles(r.Context(), projectID, files); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to update files"})
		return
	}

	// Re-read canonical DB records after ReplaceProjectFiles.
	// If the repository assigns IDs during insert, req.Files will not contain those IDs.
	savedFiles, err := s.repo.ListProjectFiles(r.Context(), projectID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to reload files"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"status": "ok",
		"files":  savedFiles,
	})
}
