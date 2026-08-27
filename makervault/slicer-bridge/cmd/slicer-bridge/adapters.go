package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
)

const adapterCatalogVersion = 1

type AdapterPlatform struct {
	Executables []string `json:"executables"`
	Args        []string `json:"args"`
}

type AdapterManifest struct {
	Version      int                        `json:"version"`
	ID           string                     `json:"id"`
	Label        string                     `json:"label"`
	LegacyTools  []string                   `json:"legacy_tools,omitempty"`
	ContentRoles []string                   `json:"content_roles"`
	Extensions   []string                   `json:"extensions"`
	Platforms    map[string]AdapterPlatform `json:"platforms"`
}

type CustomAdapterConfig struct {
	Enabled      bool     `json:"enabled"`
	Label        string   `json:"label"`
	Command      string   `json:"command"`
	Args         []string `json:"args"`
	LegacyTools  []string `json:"legacy_tools,omitempty"`
	ContentRoles []string `json:"content_roles"`
	Extensions   []string `json:"extensions"`
}

type ResolvedAdapter struct {
	Manifest     AdapterManifest
	Command      string
	Args         []string
	LegacyConfig bool
}

var allowedContentRoles = map[string]bool{
	"primary": true, "revision_primary": true, "supporting": true, "prepared": true,
}

var allowedAdapterExtensions = map[string]bool{
	".stl": true, ".3mf": true, ".step": true, ".stp": true, ".obj": true,
	".gcode": true, ".gco": true, ".bgcode": true, ".svg": true, ".dxf": true,
	".ai": true, ".eps": true, ".pdf": true, ".plt": true, ".hpgl": true,
	".png": true, ".jpg": true, ".jpeg": true, ".webp": true, ".bmp": true,
	".gif": true, ".tif": true, ".tiff": true, ".lbrn": true, ".lbrn2": true,
	".ezd": true,
}

var builtInAdapterCatalog = []AdapterManifest{
	slicerManifest("orca", "OrcaSlicer", []string{"OrcaSlicer\\OrcaSlicer.exe"}, []string{"orca-slicer", "OrcaSlicer"}, []string{"/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"}),
	slicerManifest("bambu", "Bambu Studio", []string{"Bambu Studio\\BambuStudio.exe"}, []string{"bambu-studio", "BambuStudio"}, []string{"/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"}),
	slicerManifest("prusa", "PrusaSlicer", []string{"PrusaSlicer\\PrusaSlicer.exe"}, []string{"prusa-slicer", "PrusaSlicer"}, []string{"/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"}),
	slicerManifest("superslicer", "SuperSlicer", []string{"SuperSlicer\\SuperSlicer.exe"}, []string{"superslicer", "SuperSlicer"}, []string{"/Applications/SuperSlicer.app/Contents/MacOS/SuperSlicer"}),
	slicerManifest("cura", "UltiMaker Cura", []string{"UltiMaker Cura\\UltiMaker Cura.exe", "Ultimaker Cura\\Ultimaker Cura.exe"}, []string{"cura", "UltiMaker-Cura", "Cura"}, []string{"/Applications/UltiMaker Cura.app/Contents/MacOS/UltiMaker-Cura", "/Applications/Ultimaker Cura.app/Contents/MacOS/Cura"}),
	slicerManifest("ideamaker", "ideaMaker", []string{"ideaMaker\\ideaMaker.exe"}, []string{"ideamaker", "ideaMaker"}, []string{"/Applications/ideaMaker.app/Contents/MacOS/ideaMaker"}),
	slicerManifest("simplify3d", "Simplify3D", []string{"Simplify3D\\Simplify3D.exe"}, []string{"simplify3d", "Simplify3D"}, []string{"/Applications/Simplify3D.app/Contents/MacOS/Simplify3D"}),
	slicerManifest("kisslicer", "KISSlicer", []string{"KISSlicer\\KISSlicer.exe"}, []string{"KISSlicer"}, []string{"/Applications/KISSlicer.app/Contents/MacOS/KISSlicer"}),
	slicerManifest("repetier", "Repetier-Host", []string{"Repetier-Host\\RepetierHost.exe"}, []string{"repetier-host", "RepetierHost"}, nil),
	slicerManifest("chitubox", "CHITUBOX", []string{"CHITUBOX\\CHITUBOX.exe"}, []string{"chitubox", "CHITUBOX"}, []string{"/Applications/CHITUBOX.app/Contents/MacOS/CHITUBOX"}),
	slicerManifest("lychee", "Lychee Slicer", []string{"LycheeSlicer\\LycheeSlicer.exe"}, []string{"lychee-slicer", "LycheeSlicer"}, []string{"/Applications/Lychee Slicer.app/Contents/MacOS/Lychee Slicer"}),
	slicerManifest("photon", "Anycubic Photon Workshop", []string{"Photon Workshop\\PhotonWorkshop.exe"}, []string{"photon-workshop", "PhotonWorkshop"}, nil),
	slicerManifest("creality", "Creality Print", []string{"Creality Print\\CrealityPrint.exe"}, []string{"creality-print", "CrealityPrint"}, []string{"/Applications/Creality Print.app/Contents/MacOS/Creality Print"}),
	laserManifest("lightburn", "LightBurn", []string{"LightBurn\\LightBurn.exe"}, []string{"lightburn", "LightBurn"}, []string{"/Applications/LightBurn.app/Contents/MacOS/LightBurn"}),
	laserManifest("ezcad", "EZCAD", []string{"EZCAD\\EZCAD.exe", "EZCAD2\\EZCAD2.exe", "EZCAD2\\EZCAD.exe"}, []string{"ezcad", "EZCAD"}, nil),
	generalManifest("freecad", "FreeCAD", []string{".step", ".stp", ".stl", ".obj", ".dxf"}, []string{"FreeCAD 1.0\\bin\\FreeCAD.exe", "FreeCAD 0.21\\bin\\FreeCAD.exe"}, []string{"freecad", "FreeCAD"}, []string{"/Applications/FreeCAD.app/Contents/MacOS/FreeCAD"}),
	generalManifest("inkscape", "Inkscape", []string{".svg", ".dxf", ".pdf", ".eps", ".ai", ".png"}, []string{"Inkscape\\bin\\inkscape.exe", "Inkscape\\inkscape.exe"}, []string{"inkscape", "Inkscape"}, []string{"/Applications/Inkscape.app/Contents/MacOS/inkscape"}),
}

func platformCatalog(windows, linux, darwin []string) map[string]AdapterPlatform {
	result := map[string]AdapterPlatform{}
	if len(windows) > 0 {
		result["windows"] = AdapterPlatform{Executables: windows, Args: []string{"{file}"}}
	}
	if len(linux) > 0 {
		result["linux"] = AdapterPlatform{Executables: linux, Args: []string{"{file}"}}
	}
	if len(darwin) > 0 {
		result["darwin"] = AdapterPlatform{Executables: darwin, Args: []string{"{file}"}}
	}
	return result
}

func slicerManifest(id, label string, windows, linux, darwin []string) AdapterManifest {
	return AdapterManifest{
		Version: adapterCatalogVersion, ID: id, Label: label,
		LegacyTools:  []string{"slicer"},
		ContentRoles: []string{"primary", "revision_primary", "prepared"},
		Extensions:   []string{".stl", ".3mf", ".step", ".stp", ".obj", ".gcode", ".gco", ".bgcode"},
		Platforms:    platformCatalog(windows, linux, darwin),
	}
}

func laserManifest(id, label string, windows, linux, darwin []string) AdapterManifest {
	return AdapterManifest{
		Version: adapterCatalogVersion, ID: id, Label: label,
		LegacyTools:  []string{"engraver"},
		ContentRoles: []string{"primary", "revision_primary", "supporting"},
		Extensions:   []string{".svg", ".dxf", ".ai", ".eps", ".pdf", ".plt", ".hpgl", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".lbrn", ".lbrn2", ".ezd"},
		Platforms:    platformCatalog(windows, linux, darwin),
	}
}

func generalManifest(id, label string, extensions, windows, linux, darwin []string) AdapterManifest {
	return AdapterManifest{
		Version: adapterCatalogVersion, ID: id, Label: label,
		ContentRoles: []string{"primary", "revision_primary", "supporting"},
		Extensions:   extensions,
		Platforms:    platformCatalog(windows, linux, darwin),
	}
}

func builtInAdapter(id string) (AdapterManifest, bool) {
	id = strings.ToLower(strings.TrimSpace(id))
	for _, adapter := range builtInAdapterCatalog {
		if adapter.ID == id {
			return adapter, true
		}
	}
	return AdapterManifest{}, false
}

func validateAdapterManifest(adapter AdapterManifest) error {
	if adapter.Version != adapterCatalogVersion {
		return fmt.Errorf("unsupported adapter version: %d", adapter.Version)
	}
	if !validApplicationID(adapter.ID) {
		return errors.New("adapter ID is invalid")
	}
	if strings.TrimSpace(adapter.Label) == "" || len(adapter.Label) > 80 {
		return errors.New("adapter label is invalid")
	}
	if err := validateUniqueValues("content role", adapter.ContentRoles, allowedContentRoles); err != nil {
		return err
	}
	legacyTools := map[string]bool{"slicer": true, "engraver": true}
	if err := validateUniqueValuesOptional("legacy tool", adapter.LegacyTools, legacyTools); err != nil {
		return err
	}
	if err := validateExtensions(adapter.Extensions); err != nil {
		return err
	}
	if len(adapter.Platforms) == 0 {
		return errors.New("adapter has no supported platform")
	}
	for platform, config := range adapter.Platforms {
		if platform != "windows" && platform != "linux" && platform != "darwin" {
			return fmt.Errorf("adapter platform is unsupported: %s", platform)
		}
		if len(config.Executables) == 0 {
			return fmt.Errorf("adapter platform %s has no executable candidate", platform)
		}
		for _, candidate := range config.Executables {
			if strings.TrimSpace(candidate) == "" || strings.ContainsRune(candidate, '\x00') {
				return fmt.Errorf("adapter platform %s has an invalid executable candidate", platform)
			}
		}
		if err := validateFileArguments(config.Args); err != nil {
			return fmt.Errorf("adapter platform %s arguments: %w", platform, err)
		}
	}
	return nil
}

func validateUniqueValues(label string, values []string, allowed map[string]bool) error {
	if len(values) == 0 {
		return fmt.Errorf("adapter has no %s", label)
	}
	return validateUniqueValuesOptional(label, values, allowed)
}

func validateUniqueValuesOptional(label string, values []string, allowed map[string]bool) error {
	seen := map[string]bool{}
	for _, value := range values {
		if !allowed[value] {
			return fmt.Errorf("adapter %s is unsupported: %s", label, value)
		}
		if seen[value] {
			return fmt.Errorf("adapter %s is duplicated: %s", label, value)
		}
		seen[value] = true
	}
	return nil
}

func validateExtensions(extensions []string) error {
	if len(extensions) == 0 {
		return errors.New("adapter has no extension")
	}
	seen := map[string]bool{}
	for _, extension := range extensions {
		if extension != strings.ToLower(extension) || !strings.HasPrefix(extension, ".") || !allowedAdapterExtensions[extension] {
			return fmt.Errorf("adapter extension is unsupported: %s", extension)
		}
		if seen[extension] {
			return fmt.Errorf("adapter extension is duplicated: %s", extension)
		}
		seen[extension] = true
	}
	return nil
}

func validateFileArguments(args []string) error {
	fileArguments := 0
	for _, argument := range args {
		if argument == "{file}" {
			fileArguments++
			continue
		}
		if strings.Contains(argument, "{file}") || strings.ContainsAny(argument, "{}\x00") {
			return errors.New("file placeholder must be one complete argument")
		}
	}
	if fileArguments != 1 {
		return errors.New("exactly one file placeholder is required")
	}
	return nil
}

func expandFileArgument(args []string, filePath string) ([]string, error) {
	if err := validateFileArguments(args); err != nil {
		return nil, err
	}
	result := make([]string, len(args))
	for index, argument := range args {
		if argument == "{file}" {
			result[index] = filePath
		} else {
			result[index] = argument
		}
	}
	return result, nil
}

func customAdapterManifest(id string, custom CustomAdapterConfig, platform string) (ResolvedAdapter, error) {
	if !custom.Enabled {
		return ResolvedAdapter{}, errors.New("custom adapter is disabled")
	}
	manifest, err := customAdapterDefinition(id, custom, platform)
	if err != nil {
		return ResolvedAdapter{}, err
	}
	command, err := canonicalLocalExecutable(custom.Command, false)
	if err != nil {
		return ResolvedAdapter{}, err
	}
	manifest.Platforms[platform] = AdapterPlatform{Executables: []string{command}, Args: custom.Args}
	return ResolvedAdapter{Manifest: manifest, Command: command, Args: append([]string{}, custom.Args...)}, nil
}

func customAdapterDefinition(id string, custom CustomAdapterConfig, platform string) (AdapterManifest, error) {
	if platform != "windows" && platform != "linux" && platform != "darwin" {
		return AdapterManifest{}, errors.New("custom adapter platform is unsupported")
	}
	command := strings.TrimSpace(custom.Command)
	if !filepath.IsAbs(command) || strings.ContainsRune(command, '\x00') {
		return AdapterManifest{}, errors.New("custom adapter command must be an absolute path")
	}
	manifest := AdapterManifest{
		Version: adapterCatalogVersion,
		ID:      strings.ToLower(strings.TrimSpace(id)), Label: strings.TrimSpace(custom.Label),
		LegacyTools: custom.LegacyTools, ContentRoles: custom.ContentRoles,
		Extensions: custom.Extensions,
		Platforms: map[string]AdapterPlatform{
			platform: {Executables: []string{command}, Args: custom.Args},
		},
	}
	if err := validateAdapterManifest(manifest); err != nil {
		return AdapterManifest{}, err
	}
	return manifest, nil
}

func canonicalLocalExecutable(command string, allowLookup bool) (string, error) {
	command = strings.TrimSpace(command)
	if command == "" || strings.ContainsRune(command, '\x00') {
		return "", errors.New("adapter command is empty or invalid")
	}
	if !filepath.IsAbs(command) {
		if !allowLookup {
			return "", errors.New("custom adapter command must be an absolute path")
		}
		resolved, err := exec.LookPath(command)
		if err != nil {
			return "", errors.New("configured adapter executable is unavailable")
		}
		command = resolved
	}
	absolute, err := filepath.Abs(command)
	if err != nil {
		return "", errors.New("adapter executable path is invalid")
	}
	canonical, err := filepath.EvalSymlinks(absolute)
	if err != nil {
		return "", errors.New("configured adapter executable is unavailable")
	}
	info, err := os.Stat(canonical)
	if err != nil || !info.Mode().IsRegular() {
		return "", errors.New("configured adapter executable is not a regular file")
	}
	if runtime.GOOS != "windows" && info.Mode().Perm()&0111 == 0 {
		return "", errors.New("configured adapter executable is not executable")
	}
	return canonical, nil
}

func resolveAdapter(id, tool string, cfg Config) (ResolvedAdapter, error) {
	id = strings.ToLower(strings.TrimSpace(id))
	if !validApplicationID(id) || (tool != "slicer" && tool != "engraver" && tool != "open") {
		return ResolvedAdapter{}, errors.New("adapter request is invalid")
	}
	manifest, builtIn := builtInAdapter(id)
	if builtIn && tool != "open" && !stringSliceContains(manifest.LegacyTools, tool) {
		return ResolvedAdapter{}, fmt.Errorf("adapter %s does not support %s", id, tool)
	}
	if custom, ok := cfg.Adapters[id]; ok {
		resolved, err := customAdapterManifest(id, custom, runtime.GOOS)
		if err != nil {
			return ResolvedAdapter{}, err
		}
		if tool != "open" && !stringSliceContains(resolved.Manifest.LegacyTools, tool) {
			return ResolvedAdapter{}, fmt.Errorf("custom adapter %s does not support %s", id, tool)
		}
		return resolved, nil
	}
	if tool == "open" {
		if !builtIn {
			return ResolvedAdapter{}, fmt.Errorf("adapter is unavailable or not configured: %s", id)
		}
		platform, ok := manifest.Platforms[runtime.GOOS]
		if !ok {
			return ResolvedAdapter{Manifest: manifest}, nil
		}
		return ResolvedAdapter{
			Manifest: manifest,
			Command:  resolveBuiltInExecutable(platform.Executables),
			Args:     append([]string{}, platform.Args...),
		}, nil
	}

	legacyConfigs := cfg.Slicers
	envPrefix := "MAKERVAULT_SLICER_"
	if tool == "engraver" {
		legacyConfigs = cfg.Engravers
		envPrefix = "MAKERVAULT_ENGRAVER_"
	}
	if legacy, ok := legacyConfigs[id]; ok && strings.TrimSpace(legacy.Command) != "" {
		command, err := canonicalLocalExecutable(legacy.Command, true)
		if err != nil {
			return ResolvedAdapter{}, err
		}
		args := append([]string{}, legacy.Args...)
		args = append(args, "{file}")
		if err := validateFileArguments(args); err != nil {
			return ResolvedAdapter{}, fmt.Errorf("legacy adapter arguments: %w", err)
		}
		if !builtIn {
			manifest = legacyManifest(id, tool, command, args)
		}
		return ResolvedAdapter{Manifest: manifest, Command: command, Args: args, LegacyConfig: true}, nil
	}
	envKey := envPrefix + strings.ToUpper(strings.ReplaceAll(id, "-", "_"))
	if value := strings.TrimSpace(os.Getenv(envKey)); value != "" {
		command, err := canonicalLocalExecutable(value, true)
		if err != nil {
			return ResolvedAdapter{}, err
		}
		args := []string{"{file}"}
		if !builtIn {
			manifest = legacyManifest(id, tool, command, args)
		}
		return ResolvedAdapter{Manifest: manifest, Command: command, Args: args, LegacyConfig: true}, nil
	}
	if !builtIn {
		return ResolvedAdapter{}, fmt.Errorf("adapter is unavailable or not configured: %s", id)
	}
	platform, ok := manifest.Platforms[runtime.GOOS]
	if !ok {
		return ResolvedAdapter{Manifest: manifest}, nil
	}
	command := resolveBuiltInExecutable(platform.Executables)
	return ResolvedAdapter{Manifest: manifest, Command: command, Args: append([]string{}, platform.Args...)}, nil
}

func stringSliceContains(values []string, expected string) bool {
	for _, value := range values {
		if value == expected {
			return true
		}
	}
	return false
}

func legacyManifest(id, tool, command string, args []string) AdapterManifest {
	extensions := sortedExtensionKeys(slicerExtensions)
	roles := []string{"primary", "revision_primary", "prepared"}
	if tool == "engraver" {
		extensions = sortedExtensionKeys(engraverExtensions)
		roles = []string{"primary", "revision_primary", "supporting"}
	}
	return AdapterManifest{
		Version: adapterCatalogVersion, ID: id, Label: id,
		LegacyTools: []string{tool}, ContentRoles: roles, Extensions: extensions,
		Platforms: map[string]AdapterPlatform{runtime.GOOS: {Executables: []string{command}, Args: args}},
	}
}

func sortedExtensionKeys(values map[string]bool) []string {
	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func resolveBuiltInExecutable(candidates []string) string {
	switch runtime.GOOS {
	case "windows":
		return findWindowsCandidates(candidates)
	case "linux":
		for _, candidate := range candidates {
			if path, err := exec.LookPath(candidate); err == nil {
				return path
			}
		}
	case "darwin":
		home, _ := os.UserHomeDir()
		for _, candidate := range darwinApplicationCandidates(candidates, home) {
			if info, err := os.Stat(candidate); err == nil && info.Mode().IsRegular() {
				return candidate
			}
		}
	}
	return ""
}

func findWindowsCandidates(candidates []string) string {
	var bases []string
	if value := os.Getenv("ProgramFiles"); value != "" {
		bases = append(bases, value)
	}
	if value := os.Getenv("ProgramFiles(x86)"); value != "" {
		bases = append(bases, value)
	}
	if value := os.Getenv("LOCALAPPDATA"); value != "" {
		bases = append(bases, value, filepath.Join(value, "Programs"))
	}
	for _, candidate := range candidates {
		if filepath.IsAbs(candidate) && fileExists(candidate) {
			return candidate
		}
		for _, base := range bases {
			path := filepath.Join(base, candidate)
			if fileExists(path) {
				return path
			}
		}
	}
	return ""
}
