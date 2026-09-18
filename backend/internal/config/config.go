package config

import (
	"os"
	"strconv"
	"strings"
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
	PublicIDLength     int
	InternalAPISecret  string
	AllowedOrigins     []string
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
		PublicIDLength:     envInt("PUBLIC_ID_LENGTH", 12),
		InternalAPISecret:  env("INTERNAL_API_SECRET", "local-dev-secret"),
		AllowedOrigins:     strings.FieldsFunc(env("ALLOWED_ORIGINS", "*"), func(r rune) bool { return r == ',' || r == ' ' }),
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
