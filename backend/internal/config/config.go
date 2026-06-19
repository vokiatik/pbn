package config

import (
	"os"
	"strconv"
)

type Config struct {
	HTTPPort           string
	PostgresDSN        string
	RedisAddr          string
	RedisPassword      string
	RedisDB            int
	RedisEventsChannel string
	StorageRoot        string
	QueueName          string
	QueueMaxSize       int64
	MaxActivePerUser   int
	WebBaseURL         string
	PublicIDLength     int
	InternalAPISecret  string
}

func Load() Config {
	return Config{
		HTTPPort:           env("HTTP_PORT", "8080"),
		PostgresDSN:        env("POSTGRES_DSN", "postgres://pbn:pbn@postgres:5432/pbn?sslmode=disable"),
		RedisAddr:          env("REDIS_ADDR", "redis:6379"),
		RedisPassword:      env("REDIS_PASSWORD", ""),
		RedisDB:            envInt("REDIS_DB", 0),
		RedisEventsChannel: env("REDIS_EVENTS_CHANNEL", "pbn:events"),
		StorageRoot:        env("STORAGE_ROOT", "/storage"),
		QueueName:          env("REDIS_QUEUE_NAME", "pbn:jobs"),
		QueueMaxSize:       int64(envInt("QUEUE_MAX_SIZE", 20)),
		MaxActivePerUser:   envInt("MAX_ACTIVE_PROJECTS_PER_CLIENT", 2),
		WebBaseURL:         env("WEB_BASE_URL", "http://localhost:5173"),
		PublicIDLength:     envInt("PUBLIC_ID_LENGTH", 12),
		InternalAPISecret:  env("INTERNAL_API_SECRET", "local-dev-secret"),
	}
}

func env(key string, fallback string) string {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	return v
}

func envInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	i, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return i
}
