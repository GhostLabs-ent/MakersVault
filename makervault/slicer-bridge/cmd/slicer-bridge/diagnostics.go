package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"runtime"
	"sort"
	"strings"
)

const currentConfigVersion = 1

func decodeConfig(data []byte) (Config, error) {
	cfg := Config{}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&cfg); err != nil {
		return Config{}, errors.New("bridge config is not valid JSON or contains an unknown field")
	}
	var trailing any
	if err := decoder.Decode(&trailing); err == nil {
		return Config{}, errors.New("bridge config contains trailing JSON data")
	} else if err != io.EOF {
		return Config{}, errors.New("bridge config contains invalid trailing data")
	}
	if cfg.Version < 0 || cfg.Version > currentConfigVersion {
		return Config{}, fmt.Errorf("bridge config version is unsupported: %d", cfg.Version)
	}
	if cfg.MaxDownloadMB < 0 {
		return Config{}, errors.New("bridge download limit cannot be negative")
	}
	normalizeConfigMaps(&cfg)
	if err := validateTrustedOrigins(cfg.TrustedOrigins); err != nil {
		return Config{}, err
	}
	for id, custom := range cfg.Adapters {
		if _, err := customAdapterDefinition(id, custom, runtime.GOOS); err != nil {
			return Config{}, redactedAdapterError(id, err.Error())
		}
	}
	return cfg, nil
}

func normalizeConfigMaps(cfg *Config) {
	if cfg.Slicers == nil {
		cfg.Slicers = map[string]SlicerConfig{}
	}
	if cfg.Engravers == nil {
		cfg.Engravers = map[string]SlicerConfig{}
	}
	if cfg.Adapters == nil {
		cfg.Adapters = map[string]CustomAdapterConfig{}
	}
}

func validateTrustedOrigins(origins []string) error {
	seen := map[string]bool{}
	for _, origin := range origins {
		normalized, err := normalizedTrustOrigin(origin)
		if err != nil {
			return errors.New("bridge config contains an invalid trusted origin")
		}
		key := strings.ToLower(normalized)
		if seen[key] {
			return errors.New("bridge config contains a duplicate trusted origin")
		}
		seen[key] = true
	}
	return nil
}

func normalizedTrustOrigin(raw string) (string, error) {
	value := strings.TrimRight(strings.TrimSpace(raw), "/")
	parsed, err := url.Parse(value)
	if err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || parsed.Path != "" {
		return "", errors.New("invalid origin")
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", errors.New("invalid origin scheme")
	}
	return value, nil
}

func writeAdapterList(writer io.Writer, cfg Config) error {
	fmt.Fprintf(writer, "catalog-version=%d\n", adapterCatalogVersion)
	adapters := append([]AdapterManifest{}, builtInAdapterCatalog...)
	sort.Slice(adapters, func(left, right int) bool { return adapters[left].ID < adapters[right].ID })
	for _, adapter := range adapters {
		status := "unsupported-platform"
		if platform, ok := adapter.Platforms[runtime.GOOS]; ok {
			status = "unavailable"
			if resolveBuiltInExecutable(platform.Executables) != "" {
				status = "installed"
			}
		}
		fmt.Fprintf(writer, "adapter=%s source=builtin status=%s label=%q\n", adapter.ID, status, adapter.Label)
	}
	ids := make([]string, 0, len(cfg.Adapters))
	for id := range cfg.Adapters {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		custom := cfg.Adapters[id]
		status := "disabled"
		if custom.Enabled {
			status = "unavailable"
			if _, err := customAdapterManifest(id, custom, runtime.GOOS); err == nil {
				status = "installed"
			}
		}
		fmt.Fprintf(writer, "adapter=%s source=local status=%s label=%q\n", id, status, custom.Label)
	}
	return nil
}

func writeDoctorReport(writer io.Writer, cfg Config) error {
	issues := 0
	for _, adapter := range builtInAdapterCatalog {
		if err := validateAdapterManifest(adapter); err != nil {
			issues++
			fmt.Fprintf(writer, "adapter=%s status=invalid\n", adapter.ID)
		}
	}
	for id, custom := range cfg.Adapters {
		if _, err := customAdapterDefinition(id, custom, runtime.GOOS); err != nil {
			issues++
			fmt.Fprintf(writer, "adapter=%s status=invalid\n", id)
		}
	}
	if err := validateTrustedOrigins(cfg.TrustedOrigins); err != nil {
		issues++
		fmt.Fprintln(writer, "trusted-origins status=invalid")
	}
	if issues > 0 {
		return fmt.Errorf("bridge doctor found %d configuration issue(s)", issues)
	}
	fmt.Fprintf(writer, "status=ok catalog-version=%d builtin=%d local=%d trusted-origins=%d\n", adapterCatalogVersion, len(builtInAdapterCatalog), len(cfg.Adapters), len(cfg.TrustedOrigins))
	return nil
}

func writeTrustList(writer io.Writer, cfg Config) {
	origins := append([]string{}, cfg.TrustedOrigins...)
	sort.Strings(origins)
	if len(origins) == 0 {
		fmt.Fprintln(writer, "No trusted MakersVault origins.")
		return
	}
	for _, origin := range origins {
		fmt.Fprintf(writer, "origin=%s\n", origin)
	}
}

func revokeTrustedOrigin(cfg *Config, raw string) bool {
	target, err := normalizedTrustOrigin(raw)
	if err != nil {
		return false
	}
	retained := make([]string, 0, len(cfg.TrustedOrigins))
	revoked := false
	for _, origin := range cfg.TrustedOrigins {
		normalized, normalizeErr := normalizedTrustOrigin(origin)
		if normalizeErr == nil && strings.EqualFold(normalized, target) {
			revoked = true
			continue
		}
		retained = append(retained, origin)
	}
	if revoked {
		cfg.TrustedOrigins = retained
	}
	return revoked
}

func redactedAdapterError(id, _ string) error {
	if !validApplicationID(strings.ToLower(strings.TrimSpace(id))) {
		id = "invalid"
	}
	return fmt.Errorf("adapter %s is invalid or unavailable; run bridge doctor locally", id)
}
