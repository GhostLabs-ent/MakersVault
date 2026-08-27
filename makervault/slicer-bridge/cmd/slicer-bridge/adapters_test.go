package main

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func TestBuiltInAdapterCatalogIsVersionedAndQualified(t *testing.T) {
	if adapterCatalogVersion != 1 {
		t.Fatalf("adapter catalog version = %d, expected 1", adapterCatalogVersion)
	}
	required := []string{
		"orca", "bambu", "prusa", "superslicer", "cura", "ideamaker",
		"simplify3d", "kisslicer", "repetier", "chitubox", "lychee",
		"photon", "creality", "lightburn", "ezcad", "freecad", "inkscape",
	}
	for _, id := range required {
		adapter, ok := builtInAdapter(id)
		if !ok {
			t.Errorf("required adapter %q is absent", id)
			continue
		}
		if adapter.ID != id || adapter.Label == "" || adapter.Version != 1 {
			t.Errorf("adapter %q has invalid identity/version: %+v", id, adapter)
		}
		if err := validateAdapterManifest(adapter); err != nil {
			t.Errorf("adapter %q is invalid: %v", id, err)
		}
	}

	for _, id := range []string{"orca", "bambu", "prusa", "cura"} {
		adapter, _ := builtInAdapter(id)
		if !stringSliceContains(adapter.ContentRoles, "prepared") {
			t.Errorf("slicer %q does not accept prepared content", id)
		}
	}
	for _, id := range []string{"lightburn", "ezcad"} {
		adapter, _ := builtInAdapter(id)
		if !stringSliceContains(adapter.LegacyTools, "engraver") {
			t.Errorf("laser adapter %q lost engraver compatibility", id)
		}
	}
	for _, id := range []string{"freecad", "inkscape"} {
		adapter, _ := builtInAdapter(id)
		if len(adapter.LegacyTools) != 0 {
			t.Errorf("new general adapter %q unexpectedly claims a legacy scheme", id)
		}
	}
}

func TestAdapterManifestValidationRejectsAuthorityExpansion(t *testing.T) {
	valid := AdapterManifest{
		Version:      1,
		ID:           "fixture",
		Label:        "Fixture",
		ContentRoles: []string{"primary"},
		Extensions:   []string{".stl"},
		Platforms: map[string]AdapterPlatform{
			"linux": {Executables: []string{"fixture"}, Args: []string{"{file}"}},
		},
	}
	if err := validateAdapterManifest(valid); err != nil {
		t.Fatalf("valid adapter rejected: %v", err)
	}

	tests := map[string]AdapterManifest{
		"future version":     func() AdapterManifest { value := valid; value.Version = 2; return value }(),
		"unsafe id":          func() AdapterManifest { value := valid; value.ID = "fixture;run"; return value }(),
		"unknown role":       func() AdapterManifest { value := valid; value.ContentRoles = []string{"machine-control"}; return value }(),
		"bare extension":     func() AdapterManifest { value := valid; value.Extensions = []string{"stl"}; return value }(),
		"wildcard extension": func() AdapterManifest { value := valid; value.Extensions = []string{".*"}; return value }(),
		"unknown platform": func() AdapterManifest {
			value := valid
			value.Platforms = map[string]AdapterPlatform{"plan9": {Executables: []string{"fixture"}, Args: []string{"{file}"}}}
			return value
		}(),
		"missing file argument": func() AdapterManifest {
			value := valid
			value.Platforms = map[string]AdapterPlatform{"linux": {Executables: []string{"fixture"}}}
			return value
		}(),
		"multiple file arguments": func() AdapterManifest {
			value := valid
			value.Platforms = map[string]AdapterPlatform{"linux": {Executables: []string{"fixture"}, Args: []string{"{file}", "{file}"}}}
			return value
		}(),
		"embedded file template": func() AdapterManifest {
			value := valid
			value.Platforms = map[string]AdapterPlatform{"linux": {Executables: []string{"fixture"}, Args: []string{"--input={file}"}}}
			return value
		}(),
	}
	for name, manifest := range tests {
		t.Run(name, func(t *testing.T) {
			if err := validateAdapterManifest(manifest); err == nil {
				t.Fatalf("invalid adapter was accepted: %+v", manifest)
			}
		})
	}
}

func TestCustomAdapterValidationAndLiteralFileExpansion(t *testing.T) {
	executable := filepath.Join(t.TempDir(), "custom-adapter")
	if runtime.GOOS == "windows" {
		executable += ".exe"
	}
	if err := os.WriteFile(executable, []byte("fixture"), 0700); err != nil {
		t.Fatal(err)
	}
	custom := CustomAdapterConfig{
		Enabled:      true,
		Label:        "Local CAD",
		Command:      executable,
		Args:         []string{"--safe", "{file}"},
		ContentRoles: []string{"primary", "supporting"},
		Extensions:   []string{".step", ".stp"},
	}
	adapter, err := customAdapterManifest("local-cad", custom, runtime.GOOS)
	if err != nil {
		t.Fatalf("valid custom adapter rejected: %v", err)
	}
	if adapter.Command != executable {
		t.Fatalf("custom executable changed unexpectedly: %q", adapter.Command)
	}
	args, err := expandFileArgument(adapter.Args, "/tmp/model.step")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(args, []string{"--safe", "/tmp/model.step"}) {
		t.Fatalf("unexpected expanded args: %v", args)
	}

	unsafe := custom
	unsafe.Args = []string{"--input={file}"}
	if _, err := customAdapterManifest("local-cad", unsafe, runtime.GOOS); err == nil {
		t.Fatal("embedded template was accepted")
	}
	unsafe = custom
	unsafe.Command = "sh"
	if _, err := customAdapterManifest("local-cad", unsafe, runtime.GOOS); err == nil {
		t.Fatal("relative custom command was accepted")
	}
	unsafe = custom
	unsafe.Extensions = []string{".exe"}
	if _, err := customAdapterManifest("local-cad", unsafe, runtime.GOOS); err == nil {
		t.Fatal("executable extension was accepted")
	}
}

func TestLegacyToolResolutionUsesCatalogAndConfigCompatibility(t *testing.T) {
	adapter, err := resolveAdapter("orca", "slicer", Config{})
	if err != nil {
		t.Fatalf("built-in slicer was not resolved from catalog: %v", err)
	}
	if !stringSliceContains(adapter.Manifest.LegacyTools, "slicer") {
		t.Fatalf("resolved adapter lost slicer role: %+v", adapter)
	}
	if _, err := resolveAdapter("lightburn", "slicer", Config{}); err == nil {
		t.Fatal("engraver adapter was accepted for slicer scheme")
	}
	if _, err := resolveAdapter("freecad", "slicer", Config{}); err == nil {
		t.Fatal("general adapter was accepted through a legacy scheme")
	}

	executable := filepath.Join(t.TempDir(), "legacy-slicer")
	if err := os.WriteFile(executable, []byte("fixture"), 0700); err != nil {
		t.Fatal(err)
	}
	cfg := Config{Slicers: map[string]SlicerConfig{
		"orca": {Command: executable, Args: []string{"--legacy"}},
	}}
	legacy, err := resolveAdapter("orca", "slicer", cfg)
	if err != nil {
		t.Fatalf("legacy local override was rejected: %v", err)
	}
	if !legacy.LegacyConfig || legacy.Command != executable {
		t.Fatalf("legacy compatibility was not explicit: %+v", legacy)
	}
	if strings.Join(legacy.Args, " ") != "--legacy {file}" {
		t.Fatalf("legacy file argument was not translated: %v", legacy.Args)
	}
}
