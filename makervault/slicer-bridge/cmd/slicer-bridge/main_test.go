package main

import (
	"strings"
	"testing"
)

func TestSanitizeFilename(t *testing.T) {
	tests := map[string]string{
		" model.3mf ":               "model.3mf",
		"../unsafe:model?.stl":      "unsafemodel.stl",
		"\x00\x01":                  "model",
		"folder\\another/file.step": "file.step",
	}

	for input, expected := range tests {
		if actual := sanitizeFilename(input); actual != expected {
			t.Fatalf("sanitizeFilename(%q) = %q, expected %q", input, actual, expected)
		}
	}
}

func TestRedactURLHidesBearerQueryValue(t *testing.T) {
	redacted := redactURL("https://vault.example/file?id=asset-1&token=secret-value")
	if strings.Contains(redacted, "secret-value") {
		t.Fatalf("redacted URL still contains the token: %s", redacted)
	}
	if !strings.Contains(redacted, "token=REDACTED") {
		t.Fatalf("redacted URL does not contain the marker: %s", redacted)
	}
}

func TestRedactURLHidesSignedFileGrant(t *testing.T) {
	redacted := redactURL("https://vault.example/asset/1/files/2?sig=secret-grant&inline=1")
	if strings.Contains(redacted, "secret-grant") {
		t.Fatalf("redacted URL still contains the grant: %s", redacted)
	}
	if !strings.Contains(redacted, "sig=REDACTED") {
		t.Fatalf("redacted URL does not contain the marker: %s", redacted)
	}
	if !strings.Contains(redacted, "inline=1") {
		t.Fatalf("redacted URL dropped an unrelated query parameter: %s", redacted)
	}
}

func TestHandleProtocolRejectsUntrustedShapesBeforeDownload(t *testing.T) {
	tests := []string{
		"https://vault.example/file",
		"makersvault-slicer://delete?url=https://vault.example/file",
		"makersvault-slicer://open",
		"makersvault-slicer://open?url=file:///tmp/model.stl",
	}

	for _, raw := range tests {
		if err := handleProtocol(raw, Config{}); err == nil {
			t.Fatalf("handleProtocol(%q) unexpectedly succeeded", raw)
		}
	}
}
