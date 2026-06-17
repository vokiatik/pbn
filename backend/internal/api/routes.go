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
