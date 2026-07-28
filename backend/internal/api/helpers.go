package api

import (
	"encoding/json"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"pbn/backend/internal/repository"
	"pbn/backend/internal/service"
)

func buildOriginalProjectFile(project repository.Project) repository.ProjectFile {
	sizeBytes := int64(0)
	if info, err := os.Stat(project.OriginalFilePath); err == nil {
		sizeBytes = info.Size()
	}

	return repository.ProjectFile{
		FileType:  "original",
		Filename:  project.OriginalFilename,
		FilePath:  project.OriginalFilePath,
		MimeType:  service.MimeFromFilename(project.OriginalFilename),
		SizeBytes: sizeBytes,
	}
}

// dedupeProjectFilesByType keeps the newest file for each file_type.
// This is important for reruns: a fresh overlay.png must replace the previous
// step1_overlay record, otherwise the frontend can keep previewing old output.
func dedupeProjectFilesByType(files []repository.ProjectFile) []repository.ProjectFile {
	seen := make(map[string]int, len(files))
	out := make([]repository.ProjectFile, 0, len(files))

	for _, f := range files {
		key := f.FileType
		if key == "" {
			key = f.FilePath
		}

		if idx, ok := seen[key]; ok {
			out[idx] = f
			continue
		}

		seen[key] = len(out)
		out = append(out, f)
	}

	return out
}

func requireInlineNoCacheHeaders(w http.ResponseWriter) {
	w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
	w.Header().Set("Pragma", "no-cache")
	w.Header().Set("Expires", "0")
}

func (s *Server) requireInternalSecret(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Internal-Secret") != s.cfg.InternalAPISecret {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
			return
		}
		next.ServeHTTP(w, r)
	})
}

func validateImageFile(fh *multipart.FileHeader) error {
	ext := strings.ToLower(filepath.Ext(fh.Filename))
	if ext != ".png" && ext != ".jpg" && ext != ".jpeg" && ext != ".webp" && ext != ".heic" && ext != ".heif" {
		return errors.New("only PNG, JPEG, WEBP, HEIC, and HEIF images are allowed")
	}
	return nil
}

func saveUploadedFile(path string, src multipart.File) error {
	dst, err := os.Create(path)
	if err != nil {
		return err
	}
	defer dst.Close()
	_, err = io.Copy(dst, src)
	return err
}

func sanitizeFilename(name string) string {
	name = strings.ReplaceAll(name, "\\", "_")
	name = strings.ReplaceAll(name, "/", "_")
	name = strings.TrimSpace(name)
	if name == "" {
		return "upload.png"
	}
	return name
}

func intParam(v string, fallback int) int {
	i, err := strconv.Atoi(v)
	if err != nil || i <= 0 {
		return fallback
	}
	return i
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func isHEICFile(filename string) bool {
	ext := strings.ToLower(filepath.Ext(filename))
	return ext == ".heic" || ext == ".heif"
}
