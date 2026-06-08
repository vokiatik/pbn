package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"pbn/backend/internal/config"
	"pbn/backend/internal/repository"
	"pbn/backend/internal/service"
	"pbn/backend/internal/ws"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/cors"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
)

const (
	redisEventsChannel = "pbn:events"
)

type Server struct {
	cfg      config.Config
	repo     *repository.PostgresRepository
	queue    *service.Queue
	events   *service.EventPublisher
	hub      *ws.Hub
	redis    *redis.Client
	logger   *slog.Logger
	upgrader websocket.Upgrader
}

func NewServer(cfg config.Config, repo *repository.PostgresRepository, queue *service.Queue, events *service.EventPublisher, redisClient *redis.Client, logger *slog.Logger) *Server {
	return &Server{
		cfg:    cfg,
		repo:   repo,
		queue:  queue,
		events: events,
		hub:    ws.NewHub(),
		redis:  redisClient,
		logger: logger,
		upgrader: websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool { return true },
		},
	}
}

func (s *Server) Routes() http.Handler {
	r := chi.NewRouter()
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{"*"},
		AllowedMethods:   []string{"GET", "POST", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-Client-Token", "X-Internal-Secret"},
		ExposedHeaders:   []string{"Content-Length", "Content-Type"},
		AllowCredentials: false,
		MaxAge:           300,
	}))

	r.Get("/healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	r.Get("/ws", s.handleWS)

	r.Route("/api", func(r chi.Router) {
		r.Post("/projects", s.handleCreateProject)
		r.Get("/projects", s.handleListProjects)
		r.Get("/projects/{publicID}", s.handleGetProject)
		r.Delete("/projects/{publicID}", s.handleDeleteProject)
		r.Get("/projects/{publicID}/files/{fileID}/preview", s.handlePreviewFile)
		r.Get("/projects/{publicID}/files/{fileID}/download", s.handleDownloadFile)
		r.Post("/projects/{publicID}/attach-user", s.handleAttachUser)

		r.Post("/users/resolve", s.handleResolveUser)
		r.Post("/users", s.handleCreateUser)

		r.With(s.requireInternalSecret).Post("/internal/projects/{id}/status", s.handleInternalStatusUpdate)
		r.With(s.requireInternalSecret).Post("/internal/projects/{id}/files", s.handleInternalFilesUpdate)

		r.Post("/projects/{publicID}/steps/{step}/run", s.handleRunProjectStep)
	})

	return r
}

func (s *Server) StartRedisFanout(ctx context.Context) {
	go func() {
		pubsub := s.redis.Subscribe(ctx, redisEventsChannel)
		defer pubsub.Close()
		ch := pubsub.Channel()
		for {
			select {
			case <-ctx.Done():
				return
			case msg := <-ch:
				if msg == nil {
					continue
				}
				projectID := ""
				var payload map[string]any
				if err := json.Unmarshal([]byte(msg.Payload), &payload); err == nil {
					if v, ok := payload["project_id"].(string); ok {
						projectID = v
					}
				}
				s.hub.Broadcast(projectID, []byte(msg.Payload))
			}
		}
	}()
}

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := s.upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	projectID := r.URL.Query().Get("project_id")
	s.hub.Add(ws.Subscription{Conn: conn, ProjectID: projectID})

	for {
		if _, _, err := conn.ReadMessage(); err != nil {
			s.hub.Remove(conn)
			_ = conn.Close()
			return
		}
	}
}

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

	name := sanitizeFilename(fh.Filename)
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
	}
	w.Header().Set("Content-Type", fileRec.MimeType)
	w.Header().Set("Content-Disposition", fmt.Sprintf("%s; filename=%q", disp, fileRec.Filename))
	http.ServeFile(w, r, fileRec.FilePath)
}

type resolveUserRequest struct {
	Email string `json:"email"`
}

type createUserRequest struct {
	Email       string `json:"email"`
	Username    string `json:"username"`
	PhoneNumber string `json:"phone_number"`
}

type attachUserRequest struct {
	UserID string `json:"user_id"`
}

type runStepRequest struct {
	Parameters map[string]any `json:"parameters"`
}

func (s *Server) handleResolveUser(w http.ResponseWriter, r *http.Request) {
	var req resolveUserRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid payload"})
		return
	}
	req.Email = strings.TrimSpace(strings.ToLower(req.Email))
	if req.Email == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "email is required"})
		return
	}

	user, err := s.repo.GetUserByEmail(r.Context(), req.Email)
	if err != nil {
		if errors.Is(err, repository.ErrNotFound) {
			writeJSON(w, http.StatusOK, map[string]any{"exists": false, "requires_more_data": true})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to resolve user"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{"exists": true, "user": user})
}

func (s *Server) handleCreateUser(w http.ResponseWriter, r *http.Request) {
	var req createUserRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid payload"})
		return
	}
	if strings.TrimSpace(req.Email) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "email is required"})
		return
	}

	out, err := s.repo.CreateUser(r.Context(), repository.User{
		Email:       strings.ToLower(strings.TrimSpace(req.Email)),
		Username:    strings.TrimSpace(req.Username),
		PhoneNumber: strings.TrimSpace(req.PhoneNumber),
	})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to create user"})
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

func (s *Server) handleAttachUser(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")
	project, err := s.repo.GetProjectByPublicID(r.Context(), publicID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "project not found"})
		return
	}

	var req attachUserRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid payload"})
		return
	}
	uid, err := uuid.Parse(req.UserID)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid user id"})
		return
	}
	if err := s.repo.AttachUser(r.Context(), project.ID, uid); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to attach user"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "attached"})
}

type internalStatusRequest struct {
	Status   string `json:"status"`
	Progress int    `json:"progress"`
	Message  string `json:"message"`
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

	completed := req.Status == "completed" || req.Status == "failed"
	if err := s.repo.UpdateProjectStatus(r.Context(), projectID, req.Status, completed); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to update status"})
		return
	}

	project, err := s.repo.GetProjectByID(r.Context(), projectID)
	if err == nil {
		eventType := "status_changed"
		if req.Status == "completed" {
			eventType = "completed"
		} else if req.Status == "failed" {
			eventType = "failed"
		} else if req.Progress > 0 {
			eventType = "progress"
		}
		_ = s.events.Publish(r.Context(), map[string]any{
			"type":       eventType,
			"project_id": project.PublicID,
			"status":     req.Status,
			"value":      req.Progress,
			"message":    req.Message,
		})
	}

	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

type internalFilesUpdateRequest struct {
	Files []repository.ProjectFile `json:"files"`
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

	files := make([]repository.ProjectFile, 0, len(req.Files)+1)
	files = append(files, buildOriginalProjectFile(project))
	files = append(files, req.Files...)
	files = dedupeProjectFiles(files)
	for i := range files {
		files[i].ProjectID = projectID
	}

	if err := s.repo.ReplaceProjectFiles(r.Context(), projectID, files); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to update files"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) handleRunProjectStep(w http.ResponseWriter, r *http.Request) {
	publicID := chi.URLParam(r, "publicID")

	step, err := strconv.Atoi(chi.URLParam(r, "step"))
	if err != nil || step < 1 || step > 6 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "step must be between 1 and 6"})
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
	})

	writeJSON(w, http.StatusAccepted, map[string]any{
		"project_id": publicID,
		"step":       step,
		"status":     status,
	})
}

func buildOriginalProjectFile(project repository.Project) repository.ProjectFile {
	sizeBytes := int64(0)
	if info, err := os.Stat(project.OriginalFilePath); err == nil {
		sizeBytes = info.Size()
	}

	return repository.ProjectFile{
		FileType:  "original_upload",
		Filename:  project.OriginalFilename,
		FilePath:  project.OriginalFilePath,
		MimeType:  service.MimeFromFilename(project.OriginalFilename),
		SizeBytes: sizeBytes,
	}
}

func dedupeProjectFiles(files []repository.ProjectFile) []repository.ProjectFile {
	seen := make(map[string]struct{}, len(files))
	out := make([]repository.ProjectFile, 0, len(files))
	for _, f := range files {
		key := f.FilePath
		if key == "" {
			key = f.FileType + "|" + f.Filename
		}
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, f)
	}
	return out
}

func (s *Server) requireInternalSecret(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Internal-Secret") != s.cfg.InternalAPISecret {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
			return
		}
		next.ServeHTTP(w, r)
	})
}

func validateImageFile(fh *multipart.FileHeader) error {
	ext := strings.ToLower(filepath.Ext(fh.Filename))
	if ext != ".png" && ext != ".jpg" && ext != ".jpeg" && ext != ".webp" {
		return errors.New("only PNG, JPEG, and WEBP images are allowed")
	}
	mimeType := strings.ToLower(fh.Header.Get("Content-Type"))
	if mimeType != "image/png" && mimeType != "image/jpeg" && mimeType != "image/webp" {
		return errors.New("unsupported MIME type, only image/png, image/jpeg, and image/webp are accepted")
	}
	return nil
}

func saveUploadedFile(path string, src multipart.File) error {
	dst, err := os.Create(path)
	if err != nil {
		return err
	}
	defer dst.Close()
	_, err = io.Copy(dst, src)
	return err
}

func sanitizeFilename(name string) string {
	name = strings.ReplaceAll(name, "\\", "_")
	name = strings.ReplaceAll(name, "/", "_")
	name = strings.TrimSpace(name)
	if name == "" {
		return "upload.png"
	}
	return name
}

func intParam(v string, fallback int) int {
	i, err := strconv.Atoi(v)
	if err != nil || i <= 0 {
		return fallback
	}
	return i
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
