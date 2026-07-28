package api

import (
	"encoding/json"

	"pbn/backend/internal/repository"
)

type resolveUserRequest struct {
	Email string `json:"email"`
}

type createUserRequest struct {
	Email       string `json:"email"`
	Username    string `json:"username"`
	PhoneNumber string `json:"phone_number"`
}

type attachUserRequest struct {
	UserID string `json:"user_id"`
}

type aiSettingsRequest struct {
	Provider          string           `json:"provider"`
	Category          string           `json:"category"`
	TargetPaletteSize int              `json:"target_palette_size"`
	PreserveElements  []string         `json:"preserve_elements"`
	SimplifyElements  []string         `json:"simplify_elements"`
	PromptGuidance    string           `json:"prompt_guidance"`
	PageSize          string           `json:"page_size"`
	Orientation       string           `json:"orientation"`
	FitMode           string           `json:"fit_mode"`
	Crop              *cropRectRequest `json:"crop"`
}

type cropRectRequest struct {
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
}

type runAIPipelineRequest struct {
	Settings aiSettingsRequest `json:"settings"`
}

type selectPBNDifficultyRequest struct {
	Difficulty string `json:"difficulty"`
}

type internalPBNOptionsRequest struct {
	Options json.RawMessage `json:"options"`
}

type internalAIQualityRequest struct {
	Quality json.RawMessage `json:"quality"`
}

type internalPBNSelectionRequest struct {
	Difficulty string `json:"difficulty"`
}

type internalStatusRequest struct {
	Status       string `json:"status"`
	Progress     int    `json:"progress"`
	Stage        string `json:"stage"`
	Message      string `json:"message"`
	ErrorMessage string `json:"error_message"`
}

type internalFilesUpdateRequest struct {
	Files []repository.ProjectFile `json:"files"`
}
