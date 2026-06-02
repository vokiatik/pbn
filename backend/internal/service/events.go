package service

import (
	"context"
	"encoding/json"

	"github.com/redis/go-redis/v9"
)

type EventPublisher struct {
	redisClient *redis.Client
	channel     string
}

func NewEventPublisher(redisClient *redis.Client, channel string) *EventPublisher {
	return &EventPublisher{redisClient: redisClient, channel: channel}
}

func (e *EventPublisher) Publish(ctx context.Context, payload map[string]any) error {
	b, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return e.redisClient.Publish(ctx, e.channel, b).Err()
}
