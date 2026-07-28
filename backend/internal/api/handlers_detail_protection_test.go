package api

import (
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestNormalizeDetailProtectionCreatesBinaryMask(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 3, 1))
	source.Set(0, 0, color.RGBA{R: 20, G: 20, B: 20, A: 255})
	source.Set(1, 0, color.RGBA{R: 127, G: 127, B: 127, A: 255})
	source.Set(2, 0, color.RGBA{R: 240, G: 240, B: 240, A: 255})

	mask, selected := normalizeDetailProtection(source)

	if selected != 1 {
		t.Fatalf("expected one selected pixel, got %d", selected)
	}
	if mask.GrayAt(0, 0).Y != 0 || mask.GrayAt(1, 0).Y != 0 || mask.GrayAt(2, 0).Y != 255 {
		t.Fatalf("mask was not normalized to black and white: %v", mask.Pix)
	}
}

func TestDetailProtectionFilesRoundTrip(t *testing.T) {
	root := t.TempDir()
	maskPath := filepath.Join(root, "pipeline_ai", "input", "detail_protection.png")
	manifestPath := filepath.Join(root, "pipeline_ai", "input", "detail_protection.json")
	metadata := detailProtectionMetadata{
		Exists:          true,
		Width:           12,
		Height:          8,
		CoveragePercent: 42.5,
		SHA256:          "abc",
		UpdatedAt:       time.Unix(123, 0).UTC(),
		LargeSelection:  true,
	}

	if err := writeDetailProtectionFiles(maskPath, manifestPath, []byte("png"), metadata); err != nil {
		t.Fatal(err)
	}
	loaded, err := readDetailProtectionMetadata(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.SHA256 != metadata.SHA256 || loaded.CoveragePercent != metadata.CoveragePercent {
		t.Fatalf("metadata changed during round trip: %#v", loaded)
	}
	if err := clearDetailProtectionFiles(root); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(maskPath); !os.IsNotExist(err) {
		t.Fatalf("expected mask to be removed, got %v", err)
	}
}

func TestDetailProtectionMaskEqualityUsesPixelsNotPNGEncoding(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "mask.png")
	existing := image.NewGray(image.Rect(0, 0, 3, 2))
	existing.SetGray(1, 0, color.Gray{Y: 255})
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	encoder := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := encoder.Encode(file, existing); err != nil {
		_ = file.Close()
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}

	expected := image.NewGray(image.Rect(0, 0, 3, 2))
	expected.SetGray(1, 0, color.Gray{Y: 255})
	equal, err := detailProtectionMasksEqual(path, expected)
	if err != nil {
		t.Fatal(err)
	}
	if !equal {
		t.Fatal("expected pixel-identical masks to compare equal")
	}
	expected.SetGray(2, 1, color.Gray{Y: 255})
	equal, err = detailProtectionMasksEqual(path, expected)
	if err != nil {
		t.Fatal(err)
	}
	if equal {
		t.Fatal("expected masks with different pixels to compare unequal")
	}
}

func TestDetailProtectionEditingUsesOnlyIdleReviewedStatuses(t *testing.T) {
	for _, status := range []string{"ai_image_ready", "pbn_failed", "pbn_options_ready", "pbn_selection_failed", "ai_completed"} {
		if !canEditDetailProtection(status) {
			t.Fatalf("expected %s to allow editing", status)
		}
	}
	for _, status := range []string{"uploaded", "ai_processing", "pbn_options_processing", "deleted"} {
		if canEditDetailProtection(status) {
			t.Fatalf("expected %s to reject editing", status)
		}
	}
}
