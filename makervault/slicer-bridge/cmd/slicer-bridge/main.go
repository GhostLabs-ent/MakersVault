package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

type SlicerConfig struct {
	Command string   `json:"command"`
	Args    []string `json:"args,omitempty"`
}

type Config struct {
	DownloadDir    string                  `json:"download_dir,omitempty"`
	LogFile        string                  `json:"log_file,omitempty"`
	TrustedOrigins []string                `json:"trusted_origins,omitempty"`
	MaxDownloadMB  int                     `json:"max_download_mb,omitempty"`
	Slicers        map[string]SlicerConfig `json:"slicers,omitempty"`
	Engravers      map[string]SlicerConfig `json:"engravers,omitempty"`
}

const (
	slicerScheme  = "makersvault-slicer"
	engraveScheme = "makersvault-engrave"
)

var (
	version  = "development"
	revision = "unknown"
)

func main() {
	if len(os.Args) < 2 {
		target, err := installSelf()
		if err != nil {
			fmt.Printf("Install failed: %v\n", err)
			printUsage()
			return
		}
		fmt.Printf("Installed MakerVault Bridge at %s\n", target)
		fmt.Println("You can now use Open in Slicer and Open in Engraving Software from MakerVault.")
		return
	}

	arg := strings.TrimSpace(os.Args[1])
	switch arg {
	case "", "-h", "--help":
		printUsage()
		return
	case "-v", "--version", "version":
		fmt.Printf("MakersVault Bridge %s (%s)\n", version, revision)
		return
	case "install", "--install":
		target, err := installSelf()
		if err != nil {
			fmt.Printf("Install failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Installed MakerVault Bridge at %s\n", target)
		fmt.Println("You can now use Open in Slicer and Open in Engraving Software from MakerVault.")
		return
	}

	cfg, cfgDir := loadConfig()
	setupLogging(cfg, cfgDir)

	if err := handleProtocol(arg, cfg); err != nil {
		log.Printf("error: %v", err)
	}
}

func printUsage() {
	fmt.Println("Usage:")
	fmt.Println("  slicer-bridge --install")
	fmt.Println("  slicer-bridge --version")
	fmt.Println("  slicer-bridge <makersvault-slicer://open?...>")
	fmt.Println("  slicer-bridge <makersvault-engrave://open?...>")
}

func handleProtocol(raw string, cfg Config) error {
	request, err := parseProtocolRequest(raw)
	if err != nil {
		return err
	}
	log.Printf("open request tool=%s app=%s origin=%s filename=%s", request.Tool, request.AppID, request.Origin, request.Filename)

	var cmd string
	var args []string
	if request.Tool == "engraver" {
		cmd, args = resolveEngraverCommand(request.AppID, cfg)
	} else {
		cmd, args = resolveSlicerCommand(request.AppID, cfg)
	}
	if cmd == "" {
		return fmt.Errorf("configured %s application is unavailable: %s", request.Tool, request.AppID)
	}

	cfgDir := configDir()
	if err := ensureTrustedOrigin(request.Origin, &cfg, cfgDir); err != nil {
		return err
	}

	downloadDir := resolveDownloadDir(cfg)
	if err := os.MkdirAll(downloadDir, 0755); err != nil {
		return fmt.Errorf("create download dir: %w", err)
	}
	targetPath, err := downloadGrantedFile(request, cfg, downloadDir)
	if err != nil {
		return err
	}
	log.Printf("launch %s command=%s args=%v", request.Tool, cmd, args)
	return launchCommand(cmd, args, targetPath)
}

func setupLogging(cfg Config, cfgDir string) {
	logPath := cfg.LogFile
	if logPath == "" {
		logPath = filepath.Join(cfgDir, "bridge.log")
	}
	if err := os.MkdirAll(filepath.Dir(logPath), 0755); err != nil {
		log.SetOutput(os.Stderr)
		return
	}
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		log.SetOutput(os.Stderr)
		return
	}
	log.SetOutput(f)
}

func loadConfig() (Config, string) {
	cfgDir := configDir()
	cfgPath := filepath.Join(cfgDir, "config.json")
	cfg := Config{
		Slicers:   map[string]SlicerConfig{},
		Engravers: map[string]SlicerConfig{},
	}
	data, err := os.ReadFile(cfgPath)
	if err != nil {
		return cfg, cfgDir
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return cfg, cfgDir
	}
	if cfg.Slicers == nil {
		cfg.Slicers = map[string]SlicerConfig{}
	}
	if cfg.Engravers == nil {
		cfg.Engravers = map[string]SlicerConfig{}
	}
	return cfg, cfgDir
}

func configDir() string {
	dir, err := os.UserConfigDir()
	if err != nil || dir == "" {
		return filepath.Join(os.TempDir(), "makersvault-slicer")
	}
	return filepath.Join(dir, "makersvault-slicer")
}

func resolveDownloadDir(cfg Config) string {
	if cfg.DownloadDir != "" {
		return cfg.DownloadDir
	}
	dir, err := os.UserCacheDir()
	if err != nil || dir == "" {
		return filepath.Join(os.TempDir(), "makersvault-slicer")
	}
	return filepath.Join(dir, "makersvault-slicer")
}

func sanitizeFilename(name string) string {
	name = strings.TrimSpace(name)
	name = filepath.Base(name)
	name = strings.Map(func(r rune) rune {
		switch r {
		case '<', '>', ':', '"', '/', '\\', '|', '?', '*':
			return -1
		}
		if r < 32 {
			return -1
		}
		return r
	}, name)
	name = strings.Trim(name, " .")
	if name == "" {
		return "model"
	}
	return name
}

func uniquePath(dir, name string) string {
	ext := filepath.Ext(name)
	base := strings.TrimSuffix(name, ext)
	path := filepath.Join(dir, name)
	for i := 1; fileExists(path); i++ {
		path = filepath.Join(dir, fmt.Sprintf("%s-%d%s", base, i, ext))
	}
	return path
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func resolveSlicerCommand(id string, cfg Config) (string, []string) {
	id = strings.ToLower(strings.TrimSpace(id))
	if id == "" || id == "other" {
		return "", nil
	}

	if cfg.Slicers != nil {
		if sc, ok := cfg.Slicers[id]; ok && sc.Command != "" {
			return sc.Command, sc.Args
		}
	}

	envKey := "MAKERVAULT_SLICER_" + strings.ToUpper(strings.ReplaceAll(id, "-", "_"))
	if val := strings.TrimSpace(os.Getenv(envKey)); val != "" {
		return val, nil
	}

	switch runtime.GOOS {
	case "windows":
		return findWindowsCommand(id, windowsCandidates()), nil
	case "linux":
		return findLinuxCommand(id, linuxCandidates()), nil
	default:
		return "", nil
	}
}

func resolveEngraverCommand(id string, cfg Config) (string, []string) {
	id = strings.ToLower(strings.TrimSpace(id))
	if id == "" || id == "other" {
		return "", nil
	}

	if cfg.Engravers != nil {
		if sc, ok := cfg.Engravers[id]; ok && sc.Command != "" {
			return sc.Command, sc.Args
		}
	}

	envKey := "MAKERVAULT_ENGRAVER_" + strings.ToUpper(strings.ReplaceAll(id, "-", "_"))
	if val := strings.TrimSpace(os.Getenv(envKey)); val != "" {
		return val, nil
	}

	switch runtime.GOOS {
	case "windows":
		return findWindowsCommand(id, engraverWindowsCandidates()), nil
	case "linux":
		return findLinuxCommand(id, engraverLinuxCandidates()), nil
	default:
		return "", nil
	}
}

func findWindowsCommand(id string, candidates map[string][]string) string {
	paths := candidates[id]
	if len(paths) == 0 {
		return ""
	}
	var bases []string
	if pf := os.Getenv("ProgramFiles"); pf != "" {
		bases = append(bases, pf)
	}
	if pf86 := os.Getenv("ProgramFiles(x86)"); pf86 != "" {
		bases = append(bases, pf86)
	}
	if la := os.Getenv("LOCALAPPDATA"); la != "" {
		bases = append(bases, la, filepath.Join(la, "Programs"))
	}

	for _, rel := range paths {
		if filepath.IsAbs(rel) && fileExists(rel) {
			return rel
		}
		for _, base := range bases {
			full := filepath.Join(base, rel)
			if fileExists(full) {
				return full
			}
		}
	}
	return ""
}

func findLinuxCommand(id string, candidates map[string][]string) string {
	paths := candidates[id]
	for _, name := range paths {
		if path, err := exec.LookPath(name); err == nil {
			return path
		}
	}
	return ""
}

func windowsCandidates() map[string][]string {
	return map[string][]string{
		"orca":        {"OrcaSlicer\\OrcaSlicer.exe"},
		"bambu":       {"Bambu Studio\\BambuStudio.exe"},
		"prusa":       {"PrusaSlicer\\PrusaSlicer.exe"},
		"superslicer": {"SuperSlicer\\SuperSlicer.exe"},
		"cura":        {"UltiMaker Cura\\UltiMaker Cura.exe", "Ultimaker Cura\\Ultimaker Cura.exe"},
		"ideamaker":   {"ideaMaker\\ideaMaker.exe"},
		"simplify3d":  {"Simplify3D\\Simplify3D.exe"},
		"kisslicer":   {"KISSlicer\\KISSlicer.exe"},
		"repetier":    {"Repetier-Host\\RepetierHost.exe"},
		"chitubox":    {"CHITUBOX\\CHITUBOX.exe"},
		"lychee":      {"LycheeSlicer\\LycheeSlicer.exe"},
		"photon":      {"Photon Workshop\\PhotonWorkshop.exe"},
		"creality":    {"Creality Print\\CrealityPrint.exe"},
	}
}

func linuxCandidates() map[string][]string {
	return map[string][]string{
		"orca":        {"orca-slicer", "OrcaSlicer"},
		"bambu":       {"bambu-studio", "BambuStudio"},
		"prusa":       {"prusa-slicer", "PrusaSlicer"},
		"superslicer": {"superslicer", "SuperSlicer"},
		"cura":        {"cura", "UltiMaker-Cura", "Cura"},
		"ideamaker":   {"ideamaker", "ideaMaker"},
		"simplify3d":  {"simplify3d", "Simplify3D"},
		"kisslicer":   {"KISSlicer"},
		"repetier":    {"repetier-host", "RepetierHost"},
		"chitubox":    {"chitubox", "CHITUBOX"},
		"lychee":      {"lychee-slicer", "LycheeSlicer"},
		"photon":      {"photon-workshop", "PhotonWorkshop"},
		"creality":    {"creality-print", "CrealityPrint"},
	}
}

func engraverWindowsCandidates() map[string][]string {
	return map[string][]string{
		"lightburn": {"LightBurn\\LightBurn.exe"},
		"ezcad": {
			"EZCAD\\EZCAD.exe",
			"EZCAD2\\EZCAD2.exe",
			"EZCAD2\\EZCAD.exe",
		},
	}
}

func engraverLinuxCandidates() map[string][]string {
	return map[string][]string{
		"lightburn": {"lightburn", "LightBurn"},
		"ezcad":     {"ezcad", "EZCAD"},
	}
}

func launchCommand(cmd string, args []string, filePath string) error {
	allArgs := append([]string{}, args...)
	allArgs = append(allArgs, filePath)
	c := exec.Command(cmd, allArgs...)
	return c.Start()
}

func redactURL(raw string) string {
	parsed, err := url.Parse(raw)
	if err != nil {
		return "[invalid URL redacted]"
	}
	q := parsed.Query()
	if q.Has("token") {
		q.Set("token", "REDACTED")
	}
	if q.Has("grant") {
		q.Set("grant", "REDACTED")
	}
	parsed.RawQuery = q.Encode()
	return parsed.String()
}
