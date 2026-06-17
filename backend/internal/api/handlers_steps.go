package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"pbn/backend/internal/service"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (s *Server) handleRunProjectStep(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")

	step, err := strconv.Atoi(chi.URLParam(r, "step"))
	if err != nil || step < 1 || step > 8 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "step must be between 1 and 8"})
		return
	}

	project, err := s.repo.GetProjectByPublicID(r.Context(), publicID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "project not found"})
		return
	}

	var req runStepRequest
	if r.Body != nil {
		_ = json.NewDecoder(r.Body).Decode(&req)
	}
	if req.Parameters == nil {
		req.Parameters = map[string]any{}
	}

	projectRoot := filepath.Join(s.cfg.StorageRoot, "projects", publicID)
	payload := map[string]any{
		"type":          "run_step",
		"step":          step,
		"project_id":    project.ID.String(),
		"public_id":     publicID,
		"project_root":  projectRoot,
		"input_path":    project.OriginalFilePath,
		"parameters":    req.Parameters,
		"created_at":    time.Now().UTC().Format(time.RFC3339),
		"retry_count":   0,
		"max_retries":   2,
		"callback_base": fmt.Sprintf("http://backend:%s/api/internal", s.cfg.HTTPPort),
	}

	if err := s.queue.Enqueue(r.Context(), payload); err != nil {
		if errors.Is(err, service.ErrQueueFull) {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "queue is full, please try again later"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to enqueue step"})
		return
	}

	status := fmt.Sprintf("step_%d_queued", step)
	_ = s.repo.UpdateProjectStatus(r.Context(), project.ID, status, false)

	_ = s.events.Publish(r.Context(), map[string]any{
		"type":       "status_changed",
		"project_id": publicID,
		"status":     status,
		"step":       step,
		"phase":      "queued",
	})

	writeJSON(w, http.StatusAccepted, map[string]any{
		"project_id": publicID,
		"step":       step,
		"status":     status,
	})
}

func (s *Server) handleInternalStatusUpdate(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	projectID, err := uuid.Parse(id)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid project id"})
		return
	}

	var req internalStatusRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid payload"})
		return
	}

	markProjectDone := statusMarksProjectDone(req.Status)
	if err := s.repo.UpdateProjectStatus(r.Context(), projectID, req.Status, markProjectDone); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to update status"})
		return
	}

	project, err := s.repo.GetProjectByID(r.Context(), projectID)
	if err == nil {
		step, phase, hasStep := parseStepStatus(req.Status)
		eventType := eventTypeForStatus(req.Status, req.Progress)

		payload := map[string]any{
			"type":       eventType,
			"project_id": project.PublicID,
			"status":     req.Status,
			"value":      req.Progress,
			"message":    req.Message,
		}
		if hasStep {
			payload["step"] = step
			payload["phase"] = phase
		}

		_ = s.events.Publish(r.Context(), payload)
	}

	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func parseStepStatus(status string) (step int, phase string, ok bool) {
	parts := strings.Split(status, "_")
	if len(parts) != 3 || parts[0] != "step" {
		return 0, "", false
	}

	step, err := strconv.Atoi(parts[1])
	if err != nil || step < 1 || step > 8 {
		return 0, "", false
	}

	return step, parts[2], true
}

func eventTypeForStatus(status string, progress int) string {
	if _, phase, ok := parseStepStatus(status); ok {
		switch phase {
		case "completed":
			return "step_completed"
		case "failed":
			return "failed"
		case "processing":
			if progress > 0 {
				return "progress"
			}
			return "status_changed"
		default:
			return "status_changed"
		}
	}

	switch status {
	case "completed":
		return "completed"
	case "failed":
		return "failed"
	default:
		if progress > 0 {
			return "progress"
		}
		return "status_changed"
	}
}

func statusMarksProjectDone(status string) bool {
	if status == "completed" || status == "failed" {
		return true
	}

	step, phase, ok := parseStepStatus(status)
	if !ok {
		return false
	}

	return phase == "failed" || (step == 8 && phase == "completed")
}
