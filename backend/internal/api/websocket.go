package api

import (
	"context"
	"encoding/json"
	"net/http"

	"pbn/backend/internal/ws"
)

func (s *Server) StartRedisFanout(ctx context.Context) {
	go func() {
		channel := s.cfg.RedisEventsChannel
		pubsub := s.redis.Subscribe(ctx, channel)
		defer pubsub.Close()
		ch := pubsub.Channel()
		s.logger.Info("redis event fanout started", "channel", channel)

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

				eventType, _ := payload["type"].(string)
				status, _ := payload["status"].(string)
				step, _ := payload["step"].(float64)
				fileCount := 0
				if files, ok := payload["files"].([]any); ok {
					fileCount = len(files)
				}

				s.logger.Info(
					"redis event received",
					"channel", msg.Channel,
					"type", eventType,
					"project_id", projectID,
					"status", status,
					"step", int(step),
					"file_count", fileCount,
				)
				sent := s.hub.Broadcast(projectID, []byte(msg.Payload))
				s.logger.Info(
					"websocket event sent",
					"type", eventType,
					"project_id", projectID,
					"subscriber_count", sent,
				)
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
