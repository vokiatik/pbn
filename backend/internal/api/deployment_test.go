package api

import (
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"pbn/backend/internal/config"

	"github.com/gorilla/websocket"
)

func TestProductionWebSocketOrigins(t *testing.T) {
	s := NewServer(config.Config{AllowedOrigins: []string{"https://pbn.zichka.com"}}, nil, nil, nil, nil, slog.Default())
	server := httptest.NewServer(s.Routes())
	defer server.Close()
	url := "ws" + strings.TrimPrefix(server.URL, "http") + "/ws?project_id=test"
	for _, origin := range []string{"https://pbn.zichka.com", "https://untrusted.example"} {
		conn, response, err := websocket.DefaultDialer.Dial(url, http.Header{"Origin": []string{origin}})
		if origin == "https://pbn.zichka.com" {
			if err != nil {
				t.Fatal(err)
			}
			conn.Close()
		} else if err == nil || response.StatusCode != http.StatusForbidden {
			t.Fatalf("untrusted origin must be rejected, got response %v, error %v", response, err)
		}
	}
}

func TestProductionCORSOrigins(t *testing.T) {
	s := NewServer(config.Config{AllowedOrigins: []string{"https://pbn.zichka.com"}}, nil, nil, nil, nil, slog.Default())
	for _, origin := range []string{"https://pbn.zichka.com", "https://untrusted.example"} {
		req := httptest.NewRequest(http.MethodOptions, "/api/projects", nil)
		req.Header.Set("Origin", origin)
		req.Header.Set("Access-Control-Request-Method", "POST")
		recorder := httptest.NewRecorder()
		s.Routes().ServeHTTP(recorder, req)
		allowed := recorder.Header().Get("Access-Control-Allow-Origin")
		if origin == "https://pbn.zichka.com" && allowed != origin {
			t.Fatalf("expected allowed origin %q, got %q", origin, allowed)
		}
		if origin != "https://pbn.zichka.com" && allowed != "" {
			t.Fatalf("unexpected allowed origin %q", allowed)
		}
	}
}
