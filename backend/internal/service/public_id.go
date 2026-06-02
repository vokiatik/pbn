package service

import (
	"crypto/rand"
	"encoding/base32"
	"strings"
)

func NewPublicID(length int) (string, error) {
	if length < 8 {
		length = 8
	}
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	encoded := strings.TrimRight(base32.StdEncoding.EncodeToString(buf), "=")
	encoded = strings.ToLower(encoded)
	if len(encoded) < length {
		return encoded, nil
	}
	return encoded[:length], nil
}
