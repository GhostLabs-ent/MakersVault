package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

var browserOpener = openBrowserURL

func ensureTrustedOrigin(origin string, cfg *Config, cfgDir string) error {
	if trustedOrigin(origin, cfg.TrustedOrigins) {
		return nil
	}
	confirmed, err := confirmOriginLocally(origin)
	if err != nil {
		return err
	}
	if !confirmed {
		return errors.New("MakersVault origin was not trusted")
	}
	cfg.TrustedOrigins = append(cfg.TrustedOrigins, origin)
	if err := saveConfig(*cfg, cfgDir); err != nil {
		return fmt.Errorf("save trusted origin: %w", err)
	}
	return nil
}

func trustedOrigin(origin string, trusted []string) bool {
	for _, candidate := range trusted {
		if strings.EqualFold(strings.TrimRight(strings.TrimSpace(candidate), "/"), origin) {
			return true
		}
	}
	return false
}

func confirmOriginLocally(origin string) (bool, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return false, fmt.Errorf("start local pairing confirmation: %w", err)
	}
	defer listener.Close()
	nonceBytes := make([]byte, 32)
	if _, err := rand.Read(nonceBytes); err != nil {
		return false, fmt.Errorf("create pairing nonce: %w", err)
	}
	confirmationPath := "/confirm/" + hex.EncodeToString(nonceBytes)
	result := make(chan bool, 1)
	var once sync.Once

	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		setPairingHeaders(response)
		if request.URL.Path != confirmationPath {
			http.NotFound(response, request)
			return
		}
		switch request.Method {
		case http.MethodGet:
			response.Header().Set("Content-Type", "text/html; charset=utf-8")
			fmt.Fprint(response, pairingPage(origin))
		case http.MethodPost:
			if err := request.ParseForm(); err != nil {
				http.Error(response, "Invalid confirmation", http.StatusBadRequest)
				return
			}
			trusted := request.Form.Get("decision") == "trust"
			once.Do(func() { result <- trusted })
			response.Header().Set("Content-Type", "text/html; charset=utf-8")
			if trusted {
				fmt.Fprint(response, "<!doctype html><title>MakersVault paired</title><p>Origin trusted. You may close this tab.</p>")
			} else {
				fmt.Fprint(response, "<!doctype html><title>MakersVault pairing cancelled</title><p>Pairing cancelled. You may close this tab.</p>")
			}
		default:
			response.Header().Set("Allow", "GET, POST")
			http.Error(response, "Method not allowed", http.StatusMethodNotAllowed)
		}
	})
	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       10 * time.Second,
	}
	go func() {
		_ = server.Serve(listener)
	}()
	confirmationURL := "http://" + listener.Addr().String() + confirmationPath
	if err := browserOpener(confirmationURL); err != nil {
		_ = server.Close()
		return false, fmt.Errorf("open pairing confirmation: %w", err)
	}

	var confirmed bool
	select {
	case confirmed = <-result:
	case <-time.After(90 * time.Second):
		_ = server.Close()
		return false, errors.New("MakersVault origin confirmation timed out")
	}
	shutdownContext, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownContext)
	return confirmed, nil
}

func setPairingHeaders(response http.ResponseWriter) {
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
	response.Header().Set("Referrer-Policy", "no-referrer")
	response.Header().Set("X-Content-Type-Options", "nosniff")
	response.Header().Set("X-Frame-Options", "DENY")
}

func pairingPage(origin string) string {
	warning := ""
	if strings.HasPrefix(strings.ToLower(origin), "http://") {
		warning = `<p class="warning">This origin uses unencrypted HTTP. Trust it only on a network you control.</p>`
	}
	return `<!doctype html>
<html><head><meta charset="utf-8"><title>Trust MakersVault</title>
<style>body{font:16px system-ui;background:#111827;color:#f9fafb;max-width:680px;margin:10vh auto;padding:32px;border-radius:16px}code{display:block;padding:14px;background:#030712;border-radius:8px;overflow-wrap:anywhere}.warning{color:#fbbf24}button{padding:10px 18px;margin:12px 8px 0 0;border:0;border-radius:8px;font-weight:700}.trust{background:#2563eb;color:white}</style>
</head><body><h1>Trust this MakersVault?</h1><p>A website requested permission for the bridge to receive file-scoped handoffs from:</p><code>` + html.EscapeString(origin) + `</code>` + warning + `<p>Trust only the MakersVault address you intended to use. This approval is saved on this computer.</p><form method="post"><button class="trust" name="decision" value="trust">Trust origin</button><button name="decision" value="cancel">Cancel</button></form></body></html>`
}

func saveConfig(cfg Config, cfgDir string) error {
	if err := os.MkdirAll(cfgDir, 0700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	configPath := filepath.Join(cfgDir, "config.json")
	if err := os.WriteFile(configPath, data, 0600); err != nil {
		return err
	}
	return os.Chmod(configPath, 0600)
}

func openBrowserURL(target string) error {
	switch runtime.GOOS {
	case "windows":
		return exec.Command("cmd", "/c", "start", "", target).Start()
	case "linux":
		return exec.Command("xdg-open", target).Start()
	default:
		return fmt.Errorf("unsupported OS for pairing: %s", runtime.GOOS)
	}
}
