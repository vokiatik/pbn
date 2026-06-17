package api

import "pbn/backend/internal/repository"

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

type runStepRequest struct {
	Parameters map[string]any `json:"parameters"`
}

type internalStatusRequest struct {
	Status   string `json:"status"`
	Progress int    `json:"progress"`
	Message  string `json:"message"`
}

type internalFilesUpdateRequest struct {
	Files []repository.ProjectFile `json:"files"`
}
