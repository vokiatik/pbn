package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"pbn/backend/internal/repository"
	"pbn/backend/internal/service"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func defaultAISettings(settings aiSettingsRequest) aiSettingsRequest {
	settings.Provider = normalizeAIProvider(settings.Provider)
	settings.PromptGuidance = strings.TrimSpace(settings.PromptGuidance)
	settings.PageSize = strings.ToLower(strings.TrimSpace(settings.PageSize))
	settings.Orientation = strings.ToLower(strings.TrimSpace(settings.Orientation))
	settings.FitMode = strings.ToLower(strings.TrimSpace(settings.FitMode))
	if settings.Provider == "" {
		settings.Provider = "openai"
	}
	if settings.Category == "" {
		settings.Category = "illustration"
	}
	if settings.TargetPaletteSize == 0 {
		settings.TargetPaletteSize = 24
	}
	if settings.PageSize == "" {
		settings.PageSize = "a3"
	}
	if settings.Orientation == "" {
		settings.Orientation = "portrait"
	}
	if settings.FitMode == "" {
		settings.FitMode = "cover"
	}
	if settings.FitMode == "contain" {
		settings.Crop = nil
	}
	return settings
}

func normalizeAIProvider(provider string) string {
	provider = strings.TrimSpace(strings.ToLower(provider))
	if provider == "gpt" {
		return "openai"
	}
	return provider
}

func validateAISettings(settings aiSettingsRequest) error {
	if settings.Provider != "openai" && settings.Provider != "gemini" {
		return errors.New("provider must be gpt/openai or gemini")
	}
	if len(strings.TrimSpace(settings.PromptGuidance)) > 1000 {
		return errors.New("prompt_guidance must be 1000 characters or less")
	}
	if settings.TargetPaletteSize < 8 || settings.TargetPaletteSize > 40 {
		return errors.New("target_palette_size must be between 8 and 40")
	}
	if settings.PageSize != "a3" && settings.PageSize != "a4" {
		return errors.New("page_size must be a3 or a4")
	}
	if settings.Orientation != "portrait" && settings.Orientation != "landscape" {
		return errors.New("orientation must be portrait or landscape")
	}
	if settings.FitMode != "cover" && settings.FitMode != "contain" {
		return errors.New("fit_mode must be cover or contain")
	}
	if settings.Crop != nil {
		crop := settings.Crop
		if crop.X < 0 || crop.Y < 0 || crop.Width <= 0 || crop.Height <= 0 || crop.X+crop.Width > 1.000001 || crop.Y+crop.Height > 1.000001 {
			return errors.New("crop must be a normalized rectangle inside the source image")
		}
	}
	return nil
}

func storedAISettings(project repository.Project) (aiSettingsRequest, error) {
	if len(project.AISettings) == 0 || string(project.AISettings) == "{}" || string(project.AISettings) == "null" {
		return aiSettingsRequest{}, errors.New("saved AI settings are missing; regenerate the AI image before proceeding")
	}
	var settings aiSettingsRequest
	if err := json.Unmarshal(project.AISettings, &settings); err != nil {
		return aiSettingsRequest{}, errors.New("saved AI settings are invalid; regenerate the AI image before proceeding")
	}
	settings = defaultAISettings(settings)
	if err := validateAISettings(settings); err != nil {
		return aiSettingsRequest{}, err
	}
	return settings, nil
}

func (s *Server) handleRunAIPipeline(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")
	project, err := s.repo.GetProjectByPublicID(r.Context(), publicID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "project not found"})
		return
	}
	if project.PipelineVersion != "ai" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "project does not use the AI pipeline"})
		return
	}
	if !clientOwnsProject(r, project) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "you can only run generation for projects created in this browser"})
		return
	}
	if !canQueueAIImageGeneration(project.Status) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "AI image generation cannot start from the current project status"})
		return
	}

	var req runAIPipelineRequest
	if r.Body != nil {
		_ = json.NewDecoder(r.Body).Decode(&req)
	}
	settings := defaultAISettings(req.Settings)
	if err := validateAISettings(settings); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	settingsJSON, err := json.Marshal(settings)
	if err != nil || s.repo.UpdateProjectAISettings(r.Context(), project.ID, settingsJSON) != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to save AI settings"})
		return
	}
	if err := s.repo.UpdateProjectAIQuality(r.Context(), project.ID, json.RawMessage(`{}`)); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to clear stale AI quality assessment"})
		return
	}

	forceRegenerate := project.Status == "ai_image_ready" || project.Status == "pbn_failed" || project.Status == "ai_completed"
	if forceRegenerate {
		projectRoot := filepath.Join(s.cfg.StorageRoot, "projects", project.PublicID)
		if err := clearDetailProtectionFiles(projectRoot); err != nil {
			s.logger.Warn("failed to clear stale detail protection", "project_id", project.ID, "public_id", project.PublicID, "error", err)
		}
		if err := s.unregisterDownstreamAIFiles(r.Context(), project.ID); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to clear stale generated files"})
			return
		}
		if err := clearAIDownstreamProjectFiles(projectRoot); err != nil {
			s.logger.Warn("failed to clear stale AI downstream files", "project_id", project.ID, "public_id", project.PublicID, "error", err)
		}
	}

	if err := s.enqueueAIImageGeneration(r, project, settings, forceRegenerate); err != nil {
		if errors.Is(err, service.ErrQueueFull) {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "queue is full, please try again later"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to enqueue AI image generation"})
		return
	}

	writeJSON(w, http.StatusAccepted, map[string]any{
		"project_id": publicID,
		"status":     "ai_image_queued",
	})
}

func (s *Server) handleProceedAIPipeline(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")
	project, err := s.repo.GetProjectByPublicID(r.Context(), publicID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "project not found"})
		return
	}
	if project.PipelineVersion != "ai" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "project does not use the AI pipeline"})
		return
	}
	if !clientOwnsProject(r, project) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "you can only proceed with projects created in this browser"})
		return
	}
	if project.Status != "ai_image_ready" && project.Status != "pbn_failed" && project.Status != "pbn_options_ready" && project.Status != "pbn_selection_failed" && project.Status != "ai_completed" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "PBN generation can proceed only after an AI image is ready"})
		return
	}

	settings, err := storedAISettings(project)
	if err != nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": err.Error()})
		return
	}

	if err := s.enqueuePBNContinuation(r, project, settings); err != nil {
		if errors.Is(err, service.ErrQueueFull) {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "queue is full, please try again later"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to enqueue PBN generation"})
		return
	}

	writeJSON(w, http.StatusAccepted, map[string]any{
		"project_id": publicID,
		"status":     "pbn_options_queued",
	})
}

func (s *Server) handleSelectPBNDifficulty(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")
	project, err := s.repo.GetProjectByPublicID(r.Context(), publicID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "project not found"})
		return
	}
	if !clientOwnsProject(r, project) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "you can only select options for projects created in this browser"})
		return
	}
	if project.Status != "pbn_options_ready" && project.Status != "ai_completed" && project.Status != "pbn_selection_failed" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "PBN difficulty options are not ready"})
		return
	}
	var req selectPBNDifficultyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON body"})
		return
	}
	req.Difficulty = strings.ToLower(strings.TrimSpace(req.Difficulty))
	if req.Difficulty != "hard" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "only hard PBN output is supported"})
		return
	}
	if !savedOptionExists(project.PBNOptions, req.Difficulty) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "selected difficulty is not available for this project"})
		return
	}
	settings, err := storedAISettings(project)
	if err != nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": err.Error()})
		return
	}
	if err := s.enqueuePBNSelection(r, project, settings, req.Difficulty); err != nil {
		if errors.Is(err, service.ErrQueueFull) {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "queue is full, please try again later"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to enqueue PBN selection"})
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{"project_id": publicID, "status": "pbn_selection_queued", "difficulty": req.Difficulty})
}

func (s *Server) enqueueAIImageGeneration(r *http.Request, project repository.Project, settings aiSettingsRequest, forceRegenerate bool) error {
	publicID := project.PublicID
	clearError := ""
	if err := s.repo.UpdateProjectPBNOptions(r.Context(), project.ID, json.RawMessage(`[]`)); err != nil {
		return err
	}
	if err := s.repo.UpdateProjectStatus(r.Context(), project.ID, "ai_image_queued", false, &clearError); err != nil {
		return err
	}

	payload := map[string]any{
		"type":             "generate_ai_image",
		"project_id":       project.ID.String(),
		"public_id":        publicID,
		"project_root":     filepath.Join(s.cfg.StorageRoot, "projects", publicID),
		"input_path":       project.OriginalFilePath,
		"settings":         settings,
		"force_regenerate": forceRegenerate,
		"created_at":       time.Now().UTC().Format(time.RFC3339),
		"retry_count":      0,
		"max_retries":      2,
		"callback_base":    fmt.Sprintf("http://backend:%s/api/internal", s.cfg.HTTPPort),
	}
	if err := s.queue.Enqueue(r.Context(), payload); err != nil {
		_ = s.repo.UpdateProjectStatus(r.Context(), project.ID, project.Status, statusMarksProjectDone(project.Status), nil)
		return err
	}

	_ = s.events.Publish(r.Context(), map[string]any{
		"type":       "ai_status_changed",
		"project_id": publicID,
		"status":     "ai_image_queued",
		"phase":      "queued",
	})
	return nil
}

func (s *Server) enqueuePBNContinuation(r *http.Request, project repository.Project, settings aiSettingsRequest) error {
	publicID := project.PublicID
	clearError := ""
	if err := s.repo.UpdateProjectStatus(r.Context(), project.ID, "pbn_options_queued", false, &clearError); err != nil {
		return err
	}

	payload := map[string]any{
		"type":          "generate_pbn_options",
		"project_id":    project.ID.String(),
		"public_id":     publicID,
		"project_root":  filepath.Join(s.cfg.StorageRoot, "projects", publicID),
		"input_path":    project.OriginalFilePath,
		"settings":      settings,
		"created_at":    time.Now().UTC().Format(time.RFC3339),
		"retry_count":   0,
		"max_retries":   2,
		"callback_base": fmt.Sprintf("http://backend:%s/api/internal", s.cfg.HTTPPort),
	}
	if err := s.queue.Enqueue(r.Context(), payload); err != nil {
		_ = s.repo.UpdateProjectStatus(r.Context(), project.ID, project.Status, statusMarksProjectDone(project.Status), nil)
		return err
	}

	_ = s.events.Publish(r.Context(), map[string]any{
		"type":       "ai_status_changed",
		"project_id": publicID,
		"status":     "pbn_options_queued",
		"phase":      "queued",
	})
	return nil
}

func (s *Server) enqueuePBNSelection(r *http.Request, project repository.Project, settings aiSettingsRequest, difficulty string) error {
	clearError := ""
	if err := s.repo.UpdateProjectStatus(r.Context(), project.ID, "pbn_selection_queued", false, &clearError); err != nil {
		return err
	}
	payload := map[string]any{
		"type": "finalize_pbn_option", "project_id": project.ID.String(), "public_id": project.PublicID,
		"project_root": filepath.Join(s.cfg.StorageRoot, "projects", project.PublicID), "input_path": project.OriginalFilePath,
		"settings": settings, "difficulty": difficulty, "created_at": time.Now().UTC().Format(time.RFC3339),
		"retry_count": 0, "max_retries": 2, "callback_base": fmt.Sprintf("http://backend:%s/api/internal", s.cfg.HTTPPort),
	}
	if err := s.queue.Enqueue(r.Context(), payload); err != nil {
		_ = s.repo.UpdateProjectStatus(r.Context(), project.ID, project.Status, statusMarksProjectDone(project.Status), nil)
		return err
	}
	_ = s.events.Publish(r.Context(), map[string]any{"type": "ai_status_changed", "project_id": project.PublicID, "status": "pbn_selection_queued", "phase": "queued"})
	return nil
}

func savedOptionExists(raw json.RawMessage, difficulty string) bool {
	if difficulty != "hard" {
		return false
	}
	var options []struct {
		Difficulty string `json:"difficulty"`
		Status     string `json:"status"`
	}
	if json.Unmarshal(raw, &options) != nil {
		return false
	}
	for _, option := range options {
		if option.Difficulty == difficulty && option.Status == "valid" {
			return true
		}
	}
	return false
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

	errorMessage := projectStatusErrorMessage(req)
	if err := s.repo.UpdateProjectStatus(r.Context(), projectID, req.Status, statusMarksProjectDone(req.Status), errorMessage); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to update status"})
		return
	}

	s.publishInternalStatusEvent(r.Context(), projectID, req)

	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "applied": true})
}

func (s *Server) handleInternalPBNOptionsUpdate(w http.ResponseWriter, r *http.Request) {
	projectID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid project id"})
		return
	}
	var req internalPBNOptionsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || !json.Valid(req.Options) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid PBN options"})
		return
	}
	var options []map[string]any
	if err := json.Unmarshal(req.Options, &options); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "PBN options must be an array"})
		return
	}
	if len(options) != 1 || options[0]["difficulty"] != "hard" || options[0]["status"] != "valid" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "expected one valid hard PBN option"})
		return
	}
	if err := s.unregisterDownstreamAIFiles(r.Context(), projectID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to replace stale PBN files"})
		return
	}
	if err := s.repo.UpdateProjectPBNOptions(r.Context(), projectID, req.Options); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to save PBN options"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"options": options})
}

func (s *Server) handleInternalAIQualityUpdate(w http.ResponseWriter, r *http.Request) {
	projectID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid project id"})
		return
	}
	var req internalAIQualityRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid quality assessment"})
		return
	}
	var quality struct {
		Status  string         `json:"status"`
		Codes   []string       `json:"codes"`
		Message string         `json:"message"`
		Metrics map[string]any `json:"metrics"`
	}
	if err := json.Unmarshal(req.Quality, &quality); err != nil || (quality.Status != "pass" && quality.Status != "warn") || quality.Metrics == nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "quality assessment must include pass/warn status and metrics"})
		return
	}
	if err := s.repo.UpdateProjectAIQuality(r.Context(), projectID, req.Quality); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to save AI quality assessment"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"quality": quality})
}

func (s *Server) handleInternalPBNSelectionUpdate(w http.ResponseWriter, r *http.Request) {
	projectID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid project id"})
		return
	}
	var req internalPBNSelectionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid selection"})
		return
	}
	if req.Difficulty != "hard" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid difficulty"})
		return
	}
	if err := s.repo.UpdateSelectedPBNDifficulty(r.Context(), projectID, &req.Difficulty); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to save selection"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"difficulty": req.Difficulty})
}

func (s *Server) publishInternalStatusEvent(ctx context.Context, projectID uuid.UUID, req internalStatusRequest) {
	project, err := s.repo.GetProjectByID(ctx, projectID)
	if err != nil {
		s.logger.Warn("failed to load project for status event", "project_id", projectID.String(), "error", err)
		return
	}

	eventType := "status_changed"
	if strings.HasPrefix(req.Status, "ai_") || strings.HasPrefix(req.Status, "pbn_") {
		eventType = "ai_status_changed"
	}
	payload := map[string]any{
		"type":       eventType,
		"project_id": project.PublicID,
		"status":     req.Status,
		"stage":      req.Stage,
		"value":      req.Progress,
		"progress":   req.Progress,
		"message":    req.Message,
	}
	if err := s.events.Publish(ctx, payload); err != nil {
		s.logger.Warn("failed to publish status event", "project_id", project.PublicID, "error", err)
	}
}

func statusMarksProjectDone(status string) bool {
	return status == "ai_completed" || status == "ai_failed" || status == "pbn_failed" || status == "pbn_selection_failed" || status == "failed"
}

func projectStatusErrorMessage(req internalStatusRequest) *string {
	if req.ErrorMessage != "" {
		return &req.ErrorMessage
	}
	if req.Status == "ai_failed" || req.Status == "pbn_failed" || req.Status == "pbn_selection_failed" || req.Status == "failed" {
		return &req.Message
	}
	if req.Status == "ai_queued" ||
		req.Status == "ai_processing" ||
		req.Status == "ai_image_queued" ||
		req.Status == "ai_image_processing" ||
		req.Status == "ai_image_ready" ||
		req.Status == "pbn_queued" ||
		req.Status == "pbn_processing" ||
		req.Status == "pbn_options_queued" ||
		req.Status == "pbn_options_processing" ||
		req.Status == "pbn_options_ready" ||
		req.Status == "pbn_selection_queued" ||
		req.Status == "pbn_selection_processing" ||
		req.Status == "ai_completed" {
		clearError := ""
		return &clearError
	}
	return nil
}

func clientOwnsProject(r *http.Request, project repository.Project) bool {
	clientToken := strings.TrimSpace(r.Header.Get("X-Client-Token"))
	return clientToken != "" && clientToken == project.ClientToken
}

func canQueueAIImageGeneration(status string) bool {
	switch status {
	case "uploaded", "ai_failed", "ai_image_ready", "pbn_failed", "pbn_options_ready", "pbn_selection_failed", "ai_completed":
		return true
	default:
		return false
	}
}

func (s *Server) unregisterDownstreamAIFiles(ctx context.Context, projectID uuid.UUID) error {
	existing, err := s.repo.ListProjectFiles(ctx, projectID)
	if err != nil {
		return err
	}

	files := make([]repository.ProjectFile, 0, len(existing))
	for _, f := range existing {
		if downstreamAIFileTypes[f.FileType] {
			continue
		}
		files = append(files, f)
	}
	return s.repo.ReplaceProjectFiles(ctx, projectID, files)
}

var downstreamAIFileTypes = map[string]bool{
	"ai_region_map":              true,
	"ai_palette_preview":         true,
	"ai_validation_report":       true,
	"ai_numbered_template":       true,
	"ai_palette_sheet":           true,
	"ai_painted_reference":       true,
	"ai_final":                   true,
	"ai_final_palette":           true,
	"ai_template_pdf":            true,
	"ai_palette_pdf":             true,
	"ai_easy_painted_preview":    true,
	"ai_easy_template_preview":   true,
	"ai_medium_painted_preview":  true,
	"ai_medium_template_preview": true,
	"ai_hard_painted_preview":    true,
	"ai_hard_template_preview":   true,
}
