package api

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"image"
	"image/color"
	"image/png"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"pbn/backend/internal/repository"

	"github.com/go-chi/chi/v5"
)

const detailProtectionMaxBytes int64 = 4 << 20

type detailProtectionMetadata struct {
	Exists          bool      `json:"exists"`
	Width           int       `json:"width,omitempty"`
	Height          int       `json:"height,omitempty"`
	CoveragePercent float64   `json:"coverage_percent,omitempty"`
	SHA256          string    `json:"sha256,omitempty"`
	UpdatedAt       time.Time `json:"updated_at,omitempty"`
	LargeSelection  bool      `json:"large_selection,omitempty"`
}

func (s *Server) handleGetDetailProtection(w http.ResponseWriter, r *http.Request) {
	project, ok := s.detailProtectionProject(w, r)
	if !ok {
		return
	}
	_, manifestPath := detailProtectionPaths(s.cfg.StorageRoot, project.PublicID)
	metadata, err := readDetailProtectionMetadata(manifestPath)
	if errors.Is(err, os.ErrNotExist) {
		writeJSON(w, http.StatusOK, detailProtectionMetadata{Exists: false})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to read detail protection"})
		return
	}
	writeJSON(w, http.StatusOK, metadata)
}

func (s *Server) handleGetDetailProtectionMask(w http.ResponseWriter, r *http.Request) {
	project, ok := s.detailProtectionProject(w, r)
	if !ok {
		return
	}
	maskPath, _ := detailProtectionPaths(s.cfg.StorageRoot, project.PublicID)
	if _, err := os.Stat(maskPath); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "detail protection mask not found"})
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to read detail protection mask"})
		return
	}
	requireInlineNoCacheHeaders(w)
	w.Header().Set("Content-Type", "image/png")
	w.Header().Set("Content-Disposition", `inline; filename="detail_protection.png"`)
	http.ServeFile(w, r, maskPath)
}

func (s *Server) handlePutDetailProtection(w http.ResponseWriter, r *http.Request) {
	project, ok := s.detailProtectionProject(w, r)
	if !ok {
		return
	}
	if !canEditDetailProtection(project.Status) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "detail protection cannot be changed while processing is active or before an AI image is ready"})
		return
	}
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "image/png" {
		writeJSON(w, http.StatusUnsupportedMediaType, map[string]string{"error": "detail protection must be an image/png body"})
		return
	}

	projectRoot := filepath.Join(s.cfg.StorageRoot, "projects", project.PublicID)
	reviewedPath := filepath.Join(projectRoot, "pipeline_ai", "ai", "simplified.png")
	reviewedFile, err := os.Open(reviewedPath)
	if err != nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "reviewed AI image is missing"})
		return
	}
	reviewedConfig, _, configErr := image.DecodeConfig(reviewedFile)
	_ = reviewedFile.Close()
	if configErr != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to inspect reviewed AI image"})
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, detailProtectionMaxBytes)
	decoded, err := png.Decode(r.Body)
	if err != nil {
		if errors.As(err, new(*http.MaxBytesError)) {
			writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "detail protection mask must be 4 MiB or smaller"})
			return
		}
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "detail protection body is not a valid PNG"})
		return
	}
	if decoded.Bounds().Dx() != reviewedConfig.Width || decoded.Bounds().Dy() != reviewedConfig.Height {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "detail protection dimensions must match the reviewed AI image"})
		return
	}

	gray, selected := normalizeDetailProtection(decoded)
	var encoded bytes.Buffer
	if err := png.Encode(&encoded, gray); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to normalize detail protection"})
		return
	}
	digest := sha256.Sum256(encoded.Bytes())
	coverage := 100 * float64(selected) / float64(max(1, gray.Bounds().Dx()*gray.Bounds().Dy()))
	metadata := detailProtectionMetadata{
		Exists:          true,
		Width:           gray.Bounds().Dx(),
		Height:          gray.Bounds().Dy(),
		CoveragePercent: coverage,
		SHA256:          hex.EncodeToString(digest[:]),
		UpdatedAt:       time.Now().UTC(),
		LargeSelection:  coverage > 40,
	}
	maskPath, manifestPath := detailProtectionPaths(s.cfg.StorageRoot, project.PublicID)
	existing, existingErr := readDetailProtectionMetadata(manifestPath)
	unchanged, unchangedErr := detailProtectionMasksEqual(maskPath, gray)
	if existingErr == nil && unchangedErr == nil && unchanged {
		writeJSON(w, http.StatusOK, existing)
		return
	}
	if err := writeDetailProtectionFiles(maskPath, manifestPath, encoded.Bytes(), metadata); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to save detail protection"})
		return
	}
	if err := s.invalidatePBNForDetailProtection(r, project); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "detail protection was saved but stale PBN options could not be cleared"})
		return
	}
	writeJSON(w, http.StatusOK, metadata)
}

func (s *Server) handleDeleteDetailProtection(w http.ResponseWriter, r *http.Request) {
	project, ok := s.detailProtectionProject(w, r)
	if !ok {
		return
	}
	if !canEditDetailProtection(project.Status) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "detail protection cannot be changed while processing is active or before an AI image is ready"})
		return
	}
	projectRoot := filepath.Join(s.cfg.StorageRoot, "projects", project.PublicID)
	maskPath, manifestPath := detailProtectionPaths(s.cfg.StorageRoot, project.PublicID)
	_, maskErr := os.Stat(maskPath)
	_, manifestErr := os.Stat(manifestPath)
	if errors.Is(maskErr, os.ErrNotExist) && errors.Is(manifestErr, os.ErrNotExist) {
		writeJSON(w, http.StatusOK, detailProtectionMetadata{Exists: false})
		return
	}
	if err := clearDetailProtectionFiles(projectRoot); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to clear detail protection"})
		return
	}
	if err := s.invalidatePBNForDetailProtection(r, project); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "detail protection was cleared but stale PBN options could not be cleared"})
		return
	}
	writeJSON(w, http.StatusOK, detailProtectionMetadata{Exists: false})
}

func (s *Server) detailProtectionProject(w http.ResponseWriter, r *http.Request) (repository.Project, bool) {
	project, err := s.repo.GetProjectByPublicID(r.Context(), chi.URLParam(r, "publicID"))
	if err != nil {
		status := http.StatusInternalServerError
		if errors.Is(err, repository.ErrNotFound) {
			status = http.StatusNotFound
		}
		writeJSON(w, status, map[string]string{"error": "project not found"})
		return repository.Project{}, false
	}
	if !clientOwnsProject(r, project) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "you can only edit detail protection for projects created in this browser"})
		return repository.Project{}, false
	}
	return project, true
}

func (s *Server) invalidatePBNForDetailProtection(r *http.Request, project repository.Project) error {
	if err := s.unregisterDownstreamAIFiles(r.Context(), project.ID); err != nil {
		return err
	}
	if err := s.repo.UpdateProjectPBNOptions(r.Context(), project.ID, json.RawMessage(`[]`)); err != nil {
		return err
	}
	clearError := ""
	if err := s.repo.UpdateProjectStatus(r.Context(), project.ID, "ai_image_ready", false, &clearError); err != nil {
		return err
	}
	projectRoot := filepath.Join(s.cfg.StorageRoot, "projects", project.PublicID)
	if err := clearAIDownstreamProjectFiles(projectRoot); err != nil {
		return err
	}
	_ = s.events.Publish(r.Context(), map[string]any{
		"type":       "detail_protection_changed",
		"project_id": project.PublicID,
		"status":     "ai_image_ready",
	})
	return nil
}

func detailProtectionPaths(storageRoot, publicID string) (string, string) {
	inputRoot := filepath.Join(storageRoot, "projects", publicID, "pipeline_ai", "input")
	return filepath.Join(inputRoot, "detail_protection.png"), filepath.Join(inputRoot, "detail_protection.json")
}

func normalizeDetailProtection(source image.Image) (*image.Gray, int) {
	bounds := source.Bounds()
	result := image.NewGray(image.Rect(0, 0, bounds.Dx(), bounds.Dy()))
	selected := 0
	for y := 0; y < bounds.Dy(); y++ {
		for x := 0; x < bounds.Dx(); x++ {
			value := color.GrayModel.Convert(source.At(bounds.Min.X+x, bounds.Min.Y+y)).(color.Gray).Y
			if value >= 128 {
				result.SetGray(x, y, color.Gray{Y: 255})
				selected++
			}
		}
	}
	return result, selected
}

func detailProtectionMasksEqual(path string, expected *image.Gray) (bool, error) {
	file, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer file.Close()
	decoded, err := png.Decode(file)
	if err != nil {
		return false, err
	}
	actual, _ := normalizeDetailProtection(decoded)
	if actual.Bounds() != expected.Bounds() {
		return false, nil
	}
	return bytes.Equal(actual.Pix, expected.Pix), nil
}

func writeDetailProtectionFiles(maskPath, manifestPath string, mask []byte, metadata detailProtectionMetadata) error {
	if err := os.MkdirAll(filepath.Dir(maskPath), 0o755); err != nil {
		return err
	}
	if err := atomicWriteFile(maskPath, mask, 0o644); err != nil {
		return err
	}
	payload, err := json.MarshalIndent(metadata, "", "  ")
	if err != nil {
		return err
	}
	payload = append(payload, '\n')
	return atomicWriteFile(manifestPath, payload, 0o644)
}

func atomicWriteFile(path string, payload []byte, mode os.FileMode) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if err := tmp.Chmod(mode); err != nil {
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(payload); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpPath, path); err == nil {
		return nil
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return os.Rename(tmpPath, path)
}

func readDetailProtectionMetadata(path string) (detailProtectionMetadata, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return detailProtectionMetadata{}, err
	}
	var metadata detailProtectionMetadata
	if err := json.Unmarshal(payload, &metadata); err != nil {
		return detailProtectionMetadata{}, err
	}
	return metadata, nil
}

func clearDetailProtectionFiles(projectRoot string) error {
	inputRoot := filepath.Join(projectRoot, "pipeline_ai", "input")
	for _, name := range []string{"detail_protection.png", "detail_protection.json"} {
		if err := os.Remove(filepath.Join(inputRoot, name)); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	return nil
}

func canEditDetailProtection(status string) bool {
	switch status {
	case "ai_image_ready", "pbn_failed", "pbn_options_ready", "pbn_selection_failed", "ai_completed":
		return true
	default:
		return false
	}
}
