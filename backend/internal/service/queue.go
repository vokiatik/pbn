package service

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/redis/go-redis/v9"
)

var ErrQueueFull = errors.New("queue full")

type Queue struct {
	redisClient *redis.Client
	queueName   string
	maxSize     int64
}

func NewQueue(redisClient *redis.Client, queueName string, maxSize int64) *Queue {
	return &Queue{redisClient: redisClient, queueName: queueName, maxSize: maxSize}
}

func (q *Queue) Enqueue(ctx context.Context, payload map[string]any) error {
	length, err := q.redisClient.LLen(ctx, q.queueName).Result()
	if err != nil {
		return err
	}
	if length >= q.maxSize {
		return ErrQueueFull
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return q.redisClient.RPush(ctx, q.queueName, b).Err()
}

func (q *Queue) Length(ctx context.Context) (int64, error) {
	return q.redisClient.LLen(ctx, q.queueName).Result()
}
