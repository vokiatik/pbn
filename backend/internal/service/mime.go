package service

import "strings"

func MimeFromFilename(name string) string {
	n := strings.ToLower(name)
	switch {
	case strings.HasSuffix(n, ".png"):
		return "image/png"
	case strings.HasSuffix(n, ".jpg"), strings.HasSuffix(n, ".jpeg"):
		return "image/jpeg"
	case strings.HasSuffix(n, ".json"):
		return "application/json"
	case strings.HasSuffix(n, ".pdf"):
		return "application/pdf"
	default:
		return "application/octet-stream"
	}
}
