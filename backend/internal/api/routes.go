package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/cors"
)

func (s *Server) Routes() http.Handler {
	r := chi.NewRouter()
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{"*"},
		AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
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
		r.Put("/projects/{publicID}/image", s.handleReplaceProjectImage)
		r.Delete("/projects/{publicID}", s.handleDeleteProject)
		r.Get("/projects/{publicID}/files/{fileID}/preview", s.handlePreviewFile)
		r.Get("/projects/{publicID}/files/{fileID}/download", s.handleDownloadFile)
		r.Post("/projects/{publicID}/attach-user", s.handleAttachUser)
		r.Get("/projects/{publicID}/detail-protection", s.handleGetDetailProtection)
		r.Get("/projects/{publicID}/detail-protection/mask", s.handleGetDetailProtectionMask)
		r.Put("/projects/{publicID}/detail-protection", s.handlePutDetailProtection)
		r.Delete("/projects/{publicID}/detail-protection", s.handleDeleteDetailProtection)

		r.Post("/users/resolve", s.handleResolveUser)
		r.Post("/users", s.handleCreateUser)

		r.With(s.requireInternalSecret).Post("/internal/projects/{id}/status", s.handleInternalStatusUpdate)
		r.With(s.requireInternalSecret).Post("/internal/projects/{id}/files", s.handleInternalFilesUpdate)
		r.With(s.requireInternalSecret).Post("/internal/projects/{id}/pbn-options", s.handleInternalPBNOptionsUpdate)
		r.With(s.requireInternalSecret).Post("/internal/projects/{id}/ai-quality", s.handleInternalAIQualityUpdate)
		r.With(s.requireInternalSecret).Post("/internal/projects/{id}/pbn-selection", s.handleInternalPBNSelectionUpdate)

		r.Post("/projects/{publicID}/run", s.handleRunAIPipeline)
		r.Post("/projects/{publicID}/proceed", s.handleProceedAIPipeline)
		r.Post("/projects/{publicID}/select-pbn", s.handleSelectPBNDifficulty)
	})

	return r
}
