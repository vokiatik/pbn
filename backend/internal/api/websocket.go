package api

import (
	"context"
	"encoding/json"
	"net/http"

	"pbn/backend/internal/ws"
)

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
