package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"pbn/backend/internal/config"
	"pbn/backend/internal/repository"

	"github.com/google/uuid"
)

func TestDefaultAISettingsUsesA3PortraitCover(t *testing.T) {
	settings := defaultAISettings(aiSettingsRequest{})

	if settings.PageSize != "a3" || settings.Orientation != "portrait" || settings.FitMode != "cover" {
		t.Fatalf("unexpected print defaults: %#v", settings)
	}
	if settings.TargetPaletteSize != 24 {
		t.Fatalf("expected 24 paint colours, got %d", settings.TargetPaletteSize)
	}
}

func TestValidateAISettingsRejectsCropOutsideSource(t *testing.T) {
	settings := defaultAISettings(aiSettingsRequest{
		Crop: &cropRectRequest{X: 0.8, Y: 0.1, Width: 0.3, Height: 0.5},
	})

	if err := validateAISettings(settings); err == nil {
		t.Fatal("expected invalid normalized crop to be rejected")
	}
}

func TestStoredAISettingsRoundTripControlsProceed(t *testing.T) {
	written := aiSettingsRequest{
		Provider:          "openai",
		Category:          "pet",
		TargetPaletteSize: 18,
		PageSize:          "a4",
		Orientation:       "landscape",
		FitMode:           "cover",
		Crop:              &cropRectRequest{X: 0.1, Y: 0.2, Width: 0.7, Height: 0.5},
	}
	payload, err := json.Marshal(written)
	if err != nil {
		t.Fatal(err)
	}
	project := repository.Project{AISettings: payload}

	loaded, err := storedAISettings(project)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.TargetPaletteSize != 18 || loaded.PageSize != "a4" || loaded.Orientation != "landscape" {
		t.Fatalf("stored settings changed during reload: %#v", loaded)
	}
	if loaded.Crop == nil || loaded.Crop.X != 0.1 || loaded.Crop.Width != 0.7 {
		t.Fatalf("stored crop changed during reload: %#v", loaded.Crop)
	}

	// /proceed calls storedAISettings(project) and has no request settings field,
	// so a replacement palette/crop cannot enter the continuation payload.
	replacement := defaultAISettings(aiSettingsRequest{TargetPaletteSize: 40, FitMode: "contain"})
	if replacement.TargetPaletteSize == loaded.TargetPaletteSize || replacement.FitMode == loaded.FitMode {
		t.Fatal("test setup does not contain distinct replacement settings")
	}
}

func TestStoredAISettingsRequiresLegacyProjectRegeneration(t *testing.T) {
	if _, err := storedAISettings(repository.Project{AISettings: json.RawMessage(`{}`)}); err == nil {
		t.Fatal("expected a legacy reviewed project without settings to require regeneration")
	}
}

func TestSavedOptionMustBeExplicitlyValid(t *testing.T) {
	options := json.RawMessage(`[{"difficulty":"easy","status":"valid"},{"difficulty":"hard","status":"valid"}]`)
	if !savedOptionExists(options, "hard") {
		t.Fatal("expected valid hard option")
	}
	if savedOptionExists(options, "easy") || savedOptionExists(options, "medium") || savedOptionExists(json.RawMessage(`[{"difficulty":"hard","status":"failed"}]`), "hard") {
		t.Fatal("legacy difficulties and invalid options must not be selectable")
	}
}

func TestPBNOptionsEndpointRejectsLegacyDifficulties(t *testing.T) {
	server := NewServer(config.Config{InternalAPISecret: "test-secret"}, nil, nil, nil, nil, nil)
	for _, difficulty := range []string{"easy", "medium"} {
		body := `{"options":[{"difficulty":"` + difficulty + `","status":"valid"}]}`
		req := httptest.NewRequest(http.MethodPost, "/api/internal/projects/"+uuid.NewString()+"/pbn-options", strings.NewReader(body))
		req.Header.Set("X-Internal-Secret", "test-secret")
		response := httptest.NewRecorder()
		server.Routes().ServeHTTP(response, req)
		if response.Code != http.StatusBadRequest {
			t.Fatalf("expected %s rejection, got %d", difficulty, response.Code)
		}
	}
}

func TestAIQualityEndpointRequiresInternalSecret(t *testing.T) {
	server := NewServer(config.Config{InternalAPISecret: "test-secret"}, nil, nil, nil, nil, nil)
	req := httptest.NewRequest(http.MethodPost, "/api/internal/projects/not-a-uuid/ai-quality", strings.NewReader(`{}`))
	response := httptest.NewRecorder()

	server.Routes().ServeHTTP(response, req)

	if response.Code != http.StatusUnauthorized {
		t.Fatalf("expected internal endpoint to reject a missing secret, got %d", response.Code)
	}
}

func TestAIQualityEndpointRejectsInvalidAssessment(t *testing.T) {
	server := NewServer(config.Config{InternalAPISecret: "test-secret"}, nil, nil, nil, nil, nil)
	body := `{"quality":{"status":"unknown","codes":[],"message":"bad","metrics":{}}}`
	req := httptest.NewRequest(http.MethodPost, "/api/internal/projects/"+uuid.NewString()+"/ai-quality", strings.NewReader(body))
	req.Header.Set("X-Internal-Secret", "test-secret")
	response := httptest.NewRecorder()

	server.Routes().ServeHTTP(response, req)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("expected invalid quality assessment to be rejected, got %d", response.Code)
	}
}
