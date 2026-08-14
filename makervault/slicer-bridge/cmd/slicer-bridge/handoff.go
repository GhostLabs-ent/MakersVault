package main

import (
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	defaultMaxDownloadMB = 512
	maxGrantLength       = 4096
)

var slicerExtensions = map[string]bool{
	".stl": true, ".3mf": true, ".step": true, ".stp": true, ".obj": true,
	".gcode": true, ".gco": true, ".bgcode": true,
}

var engraverExtensions = map[string]bool{
	".svg": true, ".dxf": true, ".ai": true, ".eps": true, ".pdf": true,
	".plt": true, ".hpgl": true, ".png": true, ".jpg": true, ".jpeg": true,
	".webp": true, ".bmp": true, ".gif": true, ".tif": true, ".tiff": true,
	".lbrn": true, ".lbrn2": true, ".ezd": true,
}

type ProtocolRequest struct {
	Tool      string
	AppID     string
	RedeemURL string
	Origin    string
	Grant     string
	Filename  string
}

func parseProtocolRequest(raw string) (ProtocolRequest, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return ProtocolRequest{}, fmt.Errorf("parse protocol URL: %w", err)
	}
	tool := ""
	idParam := ""
	switch strings.ToLower(parsed.Scheme) {
	case slicerScheme:
		tool = "slicer"
		idParam = "slicer"
	case engraveScheme:
		tool = "engraver"
		idParam = "engraver"
	default:
		return ProtocolRequest{}, fmt.Errorf("unexpected scheme: %s", parsed.Scheme)
	}
	action := strings.Trim(parsed.Host, "/")
	if action == "" {
		action = strings.Trim(parsed.Path, "/")
	}
	if action != "open" {
		return ProtocolRequest{}, fmt.Errorf("unsupported action: %s", action)
	}

	query := parsed.Query()
	if query.Has("url") || query.Has("token") {
		return ProtocolRequest{}, errors.New("legacy arbitrary URL/session-token handoffs are not supported")
	}
	redeemURL, origin, err := validateRedemptionURL(strings.TrimSpace(query.Get("redeem")))
	if err != nil {
		return ProtocolRequest{}, err
	}
	grant := strings.TrimSpace(query.Get("grant"))
	if !validGrantShape(grant) {
		return ProtocolRequest{}, errors.New("invalid or missing handoff grant")
	}
	appID := strings.ToLower(strings.TrimSpace(query.Get(idParam)))
	if !validApplicationID(appID) || appID == "other" {
		return ProtocolRequest{}, errors.New("a specific configured application is required")
	}
	filename := sanitizeFilename(query.Get("filename"))
	return ProtocolRequest{
		Tool: tool, AppID: appID, RedeemURL: redeemURL, Origin: origin,
		Grant: grant, Filename: filename,
	}, nil
}

func validateRedemptionURL(raw string) (string, string, error) {
	if raw == "" {
		return "", "", errors.New("missing redemption URL")
	}
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Host == "" || parsed.User != nil || parsed.Opaque != "" {
		return "", "", errors.New("invalid redemption URL")
	}
	parsed.Scheme = strings.ToLower(parsed.Scheme)
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", "", errors.New("redemption URL must use HTTP or HTTPS")
	}
	if parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" || parsed.RawPath != "" {
		return "", "", errors.New("redemption URL must not contain a query, fragment, or encoded path")
	}
	if !strings.HasSuffix(parsed.Path, "/handoff/redeem") || strings.Contains(parsed.Path, "..") {
		return "", "", errors.New("unexpected handoff redemption path")
	}

	hostname := strings.ToLower(strings.TrimSuffix(parsed.Hostname(), "."))
	if hostname == "" {
		return "", "", errors.New("invalid redemption host")
	}
	port := parsed.Port()
	if port != "" {
		value, err := strconv.Atoi(port)
		if err != nil || value < 1 || value > 65535 {
			return "", "", errors.New("invalid redemption port")
		}
	}
	defaultPort := (parsed.Scheme == "https" && port == "443") || (parsed.Scheme == "http" && port == "80")
	host := hostname
	if strings.Contains(hostname, ":") {
		host = "[" + hostname + "]"
	}
	if port != "" && !defaultPort {
		host = net.JoinHostPort(hostname, port)
	}
	origin := parsed.Scheme + "://" + host
	parsed.Host = host
	return parsed.String(), origin, nil
}

func validGrantShape(grant string) bool {
	if len(grant) < 16 || len(grant) > maxGrantLength || strings.Count(grant, ".") != 2 {
		return false
	}
	for _, character := range grant {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || character == '-' || character == '_' || character == '.' {
			continue
		}
		return false
	}
	return true
}

func validApplicationID(id string) bool {
	if id == "" || len(id) > 64 {
		return false
	}
	for _, character := range id {
		if (character >= 'a' && character <= 'z') || (character >= '0' && character <= '9') || character == '-' {
			continue
		}
		return false
	}
	return true
}

func extensionAllowed(tool, filename string) bool {
	extension := strings.ToLower(filepath.Ext(filename))
	if tool == "slicer" {
		return slicerExtensions[extension]
	}
	return engraverExtensions[extension]
}

func downloadGrantedFile(request ProtocolRequest, cfg Config, downloadDir string) (targetPath string, resultErr error) {
	maxMB := cfg.MaxDownloadMB
	if maxMB <= 0 {
		maxMB = defaultMaxDownloadMB
	}
	if uint64(maxMB) > (^uint64(0)>>1)/uint64(1024*1024) {
		return "", errors.New("configured download limit is too large")
	}
	maxBytes := int64(maxMB) * 1024 * 1024

	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	client := &http.Client{
		Timeout:   5 * time.Minute,
		Transport: transport,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return errors.New("handoff redirects are not allowed")
		},
	}
	httpRequest, err := http.NewRequest(http.MethodGet, request.RedeemURL, nil)
	if err != nil {
		return "", fmt.Errorf("create redemption request: %w", err)
	}
	httpRequest.Header.Set("Authorization", "MakerVault-Handoff "+request.Grant)
	httpRequest.Header.Set("X-MakerVault-Handoff-Tool", request.Tool)
	httpRequest.Header.Set("User-Agent", "MakerVault-Bridge/5.1")
	response, err := client.Do(httpRequest)
	if err != nil {
		return "", fmt.Errorf("redeem handoff: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", fmt.Errorf("handoff redemption failed: %s", response.Status)
	}
	if response.ContentLength > maxBytes {
		return "", fmt.Errorf("handoff file exceeds %d MiB limit", maxMB)
	}

	filename := filenameFromResponse(response, request.Filename)
	if !extensionAllowed(request.Tool, filename) {
		return "", fmt.Errorf("file type is not allowed for %s handoff: %s", request.Tool, filename)
	}
	targetPath, output, err := createUniqueDownload(downloadDir, filename)
	if err != nil {
		return "", err
	}
	cleanupPath := targetPath
	complete := false
	defer func() {
		if !complete {
			output.Close()
			os.Remove(cleanupPath)
		}
	}()

	written, err := io.Copy(output, io.LimitReader(response.Body, maxBytes+1))
	if err != nil {
		return "", fmt.Errorf("save handoff file: %w", err)
	}
	if written > maxBytes {
		return "", fmt.Errorf("handoff file exceeds %d MiB limit", maxMB)
	}
	if err := output.Close(); err != nil {
		return "", fmt.Errorf("close handoff file: %w", err)
	}
	complete = true
	return targetPath, nil
}

func filenameFromResponse(response *http.Response, fallback string) string {
	value := response.Header.Get("Content-Disposition")
	if _, params, err := mime.ParseMediaType(value); err == nil {
		if filename := strings.TrimSpace(params["filename"]); filename != "" {
			return sanitizeFilename(filename)
		}
	}
	return sanitizeFilename(fallback)
}

func createUniqueDownload(dir, name string) (string, *os.File, error) {
	extension := filepath.Ext(name)
	base := strings.TrimSuffix(name, extension)
	for index := 0; ; index++ {
		candidateName := name
		if index > 0 {
			candidateName = fmt.Sprintf("%s-%d%s", base, index, extension)
		}
		candidate := filepath.Join(dir, candidateName)
		output, err := os.OpenFile(candidate, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err == nil {
			return candidate, output, nil
		}
		if !os.IsExist(err) {
			return "", nil, fmt.Errorf("create handoff file: %w", err)
		}
	}
}
