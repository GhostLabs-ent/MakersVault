package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDecodeConfigRejectsMalformedFutureAndUnsafeAdapters(t *testing.T) {
	if _, err := decodeConfig([]byte(`{"version":`)); err == nil {
		t.Fatal("malformed config was accepted")
	}
	if _, err := decodeConfig([]byte(`{"version":2}`)); err == nil {
		t.Fatal("future config version was accepted")
	}
	if _, err := decodeConfig([]byte(`{"version":1,"unexpected":true}`)); err == nil {
		t.Fatal("unknown config field was accepted")
	}
	unsafe := `{
		"version": 1,
		"adapters": {
			"unsafe": {
				"enabled": true,
				"label": "Unsafe",
				"command": "sh",
				"args": ["-c", "{file}"],
				"content_roles": ["primary"],
				"extensions": [".stl"]
			}
		}
	}`
	if _, err := decodeConfig([]byte(unsafe)); err == nil {
		t.Fatal("unsafe relative custom command was accepted")
	}

	legacy, err := decodeConfig([]byte(`{"trusted_origins":["https://vault.example"]}`))
	if err != nil {
		t.Fatalf("legacy version-0 config was rejected: %v", err)
	}
	if legacy.Version != 0 || len(legacy.TrustedOrigins) != 1 {
		t.Fatalf("legacy config changed unexpectedly: %+v", legacy)
	}
}

func TestAdapterListAndDoctorDoNotRevealLocalCommands(t *testing.T) {
	executable := filepath.Join(t.TempDir(), "private-command")
	if err := os.WriteFile(executable, []byte("fixture"), 0700); err != nil {
		t.Fatal(err)
	}
	cfg := Config{
		Version: 1,
		Adapters: map[string]CustomAdapterConfig{
			"private-cad": {
				Enabled: true, Label: "Private CAD", Command: executable,
				Args:         []string{"--secret-value", "{file}"},
				ContentRoles: []string{"primary"}, Extensions: []string{".step"},
			},
		},
	}
	var listing bytes.Buffer
	if err := writeAdapterList(&listing, cfg); err != nil {
		t.Fatal(err)
	}
	output := listing.String()
	if !strings.Contains(output, "catalog-version=1") || !strings.Contains(output, "private-cad") {
		t.Fatalf("adapter listing omitted safe identity/status: %s", output)
	}
	if strings.Contains(output, executable) || strings.Contains(output, "secret-value") {
		t.Fatalf("adapter listing disclosed local command details: %s", output)
	}

	var doctor bytes.Buffer
	if err := writeDoctorReport(&doctor, cfg); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(doctor.String(), executable) || strings.Contains(doctor.String(), "secret-value") {
		t.Fatalf("doctor disclosed local command details: %s", doctor.String())
	}
}

func TestTrustListingAndExactRevocation(t *testing.T) {
	cfg := Config{TrustedOrigins: []string{
		"https://vault.example",
		"http://vault.lan:8000",
	}}
	var listing bytes.Buffer
	writeTrustList(&listing, cfg)
	if !strings.Contains(listing.String(), "https://vault.example") {
		t.Fatalf("trusted origin was not listed: %s", listing.String())
	}
	if revokeTrustedOrigin(&cfg, "https://other.example") {
		t.Fatal("unknown origin was reported as revoked")
	}
	if !revokeTrustedOrigin(&cfg, "HTTPS://VAULT.EXAMPLE/") {
		t.Fatal("exact normalized origin was not revoked")
	}
	if len(cfg.TrustedOrigins) != 1 || cfg.TrustedOrigins[0] != "http://vault.lan:8000" {
		t.Fatalf("revocation changed the wrong origins: %v", cfg.TrustedOrigins)
	}
}

func TestRedactedErrorDoesNotExposeCommandOrArguments(t *testing.T) {
	err := redactedAdapterError("private-cad", "configured command /secret/bin/cad --token value is unavailable")
	if !strings.Contains(err.Error(), "private-cad") || strings.Contains(err.Error(), "/secret") || strings.Contains(err.Error(), "token") {
		t.Fatalf("adapter error was not safely redacted: %v", err)
	}
}
