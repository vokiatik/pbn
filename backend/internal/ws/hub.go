package ws

import (
	"sync"

	"github.com/gorilla/websocket"
)

type Subscription struct {
	Conn      *websocket.Conn
	ProjectID string
}

type Hub struct {
	mu      sync.RWMutex
	clients map[*websocket.Conn]Subscription
}

func NewHub() *Hub {
	return &Hub{clients: map[*websocket.Conn]Subscription{}}
}

func (h *Hub) Add(sub Subscription) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[sub.Conn] = sub
}

func (h *Hub) Remove(conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.clients, conn)
}

func (h *Hub) Broadcast(projectID string, payload []byte) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for _, sub := range h.clients {
		if sub.ProjectID != "" && sub.ProjectID != projectID {
			continue
		}
		_ = sub.Conn.WriteMessage(websocket.TextMessage, payload)
	}
}
