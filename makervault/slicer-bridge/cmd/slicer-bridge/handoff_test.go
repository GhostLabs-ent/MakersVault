package main

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testGrant = "aaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbb.cccccccccccccccc"

func TestParseProtocolRequestAcceptsOnlyScopedShape(t *testing.T) {
	redeem := url.QueryEscape("https://Vault.Example:443/api/handoff/redeem")
	raw := "makersvault-slicer://open?redeem=" + redeem + "&grant=" + testGrant + "&slicer=orca&filename=plate.3mf"
	request, err := parseProtocolRequest(raw)
	if err != nil {
		t.Fatalf("parseProtocolRequest returned error: %v", err)
	}
	if request.Tool != "slicer" || request.AppID != "orca" || request.Origin != "https://vault.example" {
		t.Fatalf("unexpected parsed request: %+v", request)
	}
	if request.RedeemURL != "https://vault.example/api/handoff/redeem" {
		t.Fatalf("unexpected normalized redemption URL: %s", request.RedeemURL)
	}

	rejected := []string{
		"makersvault-slicer://open?url=https://vault.example/file&grant=" + testGrant + "&slicer=orca",
		"makersvault-slicer://open?redeem=https://vault.example/api/handoff/redeem?token=admin&grant=" + testGrant + "&slicer=orca",
		"makersvault-slicer://open?redeem=https://vault.example/api/handoff/redeem&grant=" + testGrant + "&slicer=other",
		"makersvault-slicer://open?redeem=https://vault.example/elsewhere&grant=" + testGrant + "&slicer=orca",
	}
	for _, candidate := range rejected {
		if _, err := parseProtocolRequest(candidate); err == nil {
			t.Fatalf("unsafe protocol request unexpectedly accepted: %s", candidate)
		}
	}
}

func TestParseGeneralOpenRequestBindsAdapterAndContentRole(t *testing.T) {
	redeem := url.QueryEscape("https://vault.example/api/handoff/redeem")
	raw := "makersvault-open://open?redeem=" + redeem + "&grant=" + testGrant + "&adapter=freecad&role=revision_primary&filename=part.step"
	request, err := parseProtocolRequest(raw)
	if err != nil {
		t.Fatalf("general protocol request returned error: %v", err)
	}
	if request.Tool != "open" || request.AppID != "freecad" || request.ContentRole != "revision_primary" {
		t.Fatalf("general protocol identity was not preserved: %+v", request)
	}

	rejected := []string{
		"makersvault-open://open?redeem=" + redeem + "&grant=" + testGrant + "&adapter=freecad&filename=part.step",
		"makersvault-open://open?redeem=" + redeem + "&grant=" + testGrant + "&adapter=freecad&role=machine-control&filename=part.step",
		"makersvault-open://open?redeem=" + redeem + "&grant=" + testGrant + "&adapter=other&role=primary&filename=part.step",
	}
	for _, candidate := range rejected {
		if _, err := parseProtocolRequest(candidate); err == nil {
			t.Fatalf("unsafe general request was accepted: %s", candidate)
		}
	}
}

func TestGeneralAdapterAuthorizationNarrowsRoleAndExtension(t *testing.T) {
	freecad, _ := builtInAdapter("freecad")
	if !adapterAllows(freecad, "revision_primary", "part.step") {
		t.Fatal("FreeCAD rejected its approved historical STEP role")
	}
	if adapterAllows(freecad, "prepared", "plate.gcode") {
		t.Fatal("FreeCAD accepted a prepared toolpath")
	}
	if adapterAllows(freecad, "primary", "design.svg") {
		t.Fatal("FreeCAD accepted an undeclared SVG extension")
	}
	inkscape, _ := builtInAdapter("inkscape")
	if !adapterAllows(inkscape, "supporting", "drawing.svg") {
		t.Fatal("Inkscape rejected its approved supporting SVG role")
	}
}

func TestGeneralDownloadSendsBoundRoleAndAdapterHeaders(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get("X-MakerVault-Handoff-Tool") != "open" ||
			request.Header.Get("X-MakerVault-Handoff-Role") != "primary" ||
			request.Header.Get("X-MakerVault-Handoff-Adapter") != "freecad" {
			t.Errorf("general handoff headers were not bound: %v", request.Header)
		}
		response.Header().Set("Content-Disposition", `attachment; filename="part.step"`)
		_, _ = response.Write([]byte("STEP fixture"))
	}))
	defer server.Close()
	manifest, _ := builtInAdapter("freecad")
	request := ProtocolRequest{
		Tool: "open", AppID: "freecad", ContentRole: "primary",
		RedeemURL: server.URL + "/handoff/redeem", Grant: testGrant,
		Filename: "part.step", Adapter: manifest,
	}
	if _, err := downloadGrantedFile(request, Config{}, t.TempDir()); err != nil {
		t.Fatalf("general adapter download failed: %v", err)
	}
}

func TestUnavailableApplicationFailsBeforePairOrDownload(t *testing.T) {
	redeem := url.QueryEscape("https://vault.example/api/handoff/redeem")
	raw := "makersvault-slicer://open?redeem=" + redeem + "&grant=" + testGrant + "&slicer=not-installed&filename=model.stl"
	err := handleProtocol(raw, Config{})
	if err == nil || !strings.Contains(err.Error(), "unavailable") {
		t.Fatalf("missing application did not fail closed: %v", err)
	}
}

func TestDownloadGrantedFileUsesHeadersAndServerFilename(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Authorization") != "MakerVault-Handoff "+testGrant {
			t.Errorf("unexpected authorization header: %s", request.Header.Get("Authorization"))
		}
		if request.Header.Get("X-MakerVault-Handoff-Tool") != "slicer" {
			t.Errorf("unexpected tool header: %s", request.Header.Get("X-MakerVault-Handoff-Tool"))
		}
		response.Header().Set("Content-Disposition", `attachment; filename="prepared.gcode.3mf"`)
		_, _ = response.Write([]byte("prepared model"))
	}))
	defer server.Close()

	downloadDir := t.TempDir()
	request := ProtocolRequest{
		Tool: "slicer", RedeemURL: server.URL + "/handoff/redeem", Grant: testGrant,
		Filename: "fallback.stl",
	}
	target, err := downloadGrantedFile(request, Config{}, downloadDir)
	if err != nil {
		t.Fatalf("downloadGrantedFile returned error: %v", err)
	}
	if filepath.Base(target) != "prepared.gcode.3mf" {
		t.Fatalf("unexpected target filename: %s", target)
	}
	data, err := os.ReadFile(target)
	if err != nil || string(data) != "prepared model" {
		t.Fatalf("unexpected downloaded data: %q, %v", data, err)
	}
}

func TestDownloadRejectsRedirectsAndRemovesOversizedPartialFile(t *testing.T) {
	redirectServer := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		http.Redirect(response, request, "/handoff/redeem", http.StatusFound)
	}))
	defer redirectServer.Close()
	downloadDir := t.TempDir()
	request := ProtocolRequest{
		Tool: "slicer", RedeemURL: redirectServer.URL + "/handoff/redeem", Grant: testGrant,
		Filename: "model.stl",
	}
	if _, err := downloadGrantedFile(request, Config{}, downloadDir); err == nil || !strings.Contains(err.Error(), "redirect") {
		t.Fatalf("redirect was not rejected: %v", err)
	}

	oversizedServer := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Disposition", `attachment; filename="large.stl"`)
		response.Header().Set("Content-Type", "application/octet-stream")
		_, _ = io.Copy(response, bytes.NewReader(bytes.Repeat([]byte("x"), 1024*1024+1)))
	}))
	defer oversizedServer.Close()
	request.RedeemURL = oversizedServer.URL + "/handoff/redeem"
	if _, err := downloadGrantedFile(request, Config{MaxDownloadMB: 1}, downloadDir); err == nil || !strings.Contains(err.Error(), "exceeds") {
		t.Fatalf("oversized response was not rejected: %v", err)
	}
	entries, err := os.ReadDir(downloadDir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("failed downloads left files behind: %v", entries)
	}
}

func TestLocalPairingRequiresConfirmationAndPersistsOrigin(t *testing.T) {
	originalOpener := browserOpener
	defer func() { browserOpener = originalOpener }()
	browserOpener = func(target string) error {
		response, err := http.Get(target)
		if err != nil {
			return err
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil {
			return err
		}
		if !strings.Contains(string(body), "https://vault.example") {
			t.Fatalf("confirmation page omitted the exact origin: %s", body)
		}
		if response.Header.Get("Content-Security-Policy") == "" {
			t.Fatal("confirmation page omitted CSP")
		}
		_, err = http.PostForm(target, url.Values{"decision": {"trust"}})
		return err
	}

	cfg := Config{Slicers: map[string]SlicerConfig{}, Engravers: map[string]SlicerConfig{}}
	cfgDir := t.TempDir()
	if err := ensureTrustedOrigin("https://vault.example", &cfg, cfgDir); err != nil {
		t.Fatalf("ensureTrustedOrigin returned error: %v", err)
	}
	if !trustedOrigin("https://vault.example", cfg.TrustedOrigins) {
		t.Fatalf("confirmed origin was not retained: %v", cfg.TrustedOrigins)
	}
	data, err := os.ReadFile(filepath.Join(cfgDir, "config.json"))
	if err != nil || !strings.Contains(string(data), "https://vault.example") {
		t.Fatalf("confirmed origin was not persisted: %s, %v", data, err)
	}
}

func TestCancelledPairingDoesNotPersistOrigin(t *testing.T) {
	originalOpener := browserOpener
	defer func() { browserOpener = originalOpener }()
	browserOpener = func(target string) error {
		_, err := http.PostForm(target, url.Values{"decision": {"cancel"}})
		return err
	}

	cfg := Config{}
	cfgDir := t.TempDir()
	if err := ensureTrustedOrigin("https://untrusted.example", &cfg, cfgDir); err == nil {
		t.Fatal("cancelled origin was unexpectedly trusted")
	}
	if len(cfg.TrustedOrigins) != 0 {
		t.Fatalf("cancelled origin was retained: %v", cfg.TrustedOrigins)
	}
	if _, err := os.Stat(filepath.Join(cfgDir, "config.json")); !os.IsNotExist(err) {
		t.Fatalf("cancelled pairing wrote a config file: %v", err)
	}
}

func TestGrantRedactionAndRoleExtensions(t *testing.T) {
	redacted := redactURL("makersvault-slicer://open?grant=secret.grant.value&redeem=https://vault.example/handoff/redeem")
	if strings.Contains(redacted, "secret.grant.value") || !strings.Contains(redacted, "grant=REDACTED") {
		t.Fatalf("grant was not redacted: %s", redacted)
	}
	if !extensionAllowed("slicer", "plate.gcode") || extensionAllowed("engraver", "plate.gcode") {
		t.Fatal("slicer extension policy is incorrect")
	}
	if !extensionAllowed("engraver", "design.svg") || extensionAllowed("slicer", "design.svg") {
		t.Fatal("engraver extension policy is incorrect")
	}
}
