package api

import (
	"log/slog"
	"net/http"

	"pbn/backend/internal/config"
	"pbn/backend/internal/repository"
	"pbn/backend/internal/service"
	"pbn/backend/internal/ws"

	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
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

func NewServer(
	cfg config.Config,
	repo *repository.PostgresRepository,
	queue *service.Queue,
	events *service.EventPublisher,
	redisClient *redis.Client,
	logger *slog.Logger,
) *Server {
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
