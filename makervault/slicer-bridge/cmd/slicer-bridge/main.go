package main

import (
	"errors"
	"fmt"
	"log"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

type SlicerConfig struct {
	Command string   `json:"command"`
	Args    []string `json:"args,omitempty"`
}

type Config struct {
	Version        int                            `json:"version,omitempty"`
	DownloadDir    string                         `json:"download_dir,omitempty"`
	LogFile        string                         `json:"log_file,omitempty"`
	TrustedOrigins []string                       `json:"trusted_origins,omitempty"`
	MaxDownloadMB  int                            `json:"max_download_mb,omitempty"`
	Slicers        map[string]SlicerConfig        `json:"slicers,omitempty"`
	Engravers      map[string]SlicerConfig        `json:"engravers,omitempty"`
	Adapters       map[string]CustomAdapterConfig `json:"adapters,omitempty"`
}

const (
	slicerScheme  = "makersvault-slicer"
	engraveScheme = "makersvault-engrave"
	generalScheme = "makersvault-open"
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
	case "uninstall", "--uninstall":
		target, err := uninstallSelf()
		if err != nil {
			fmt.Printf("Uninstall failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Uninstalled MakerVault Bridge from %s\n", target)
		return
	}

	cfg, cfgDir, err := loadConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Bridge configuration error: %v\n", err)
		os.Exit(1)
	}
	setupLogging(cfg, cfgDir)
	switch arg {
	case "list":
		if err := writeAdapterList(os.Stdout, cfg); err != nil {
			fmt.Fprintf(os.Stderr, "Adapter listing failed: %v\n", err)
			os.Exit(1)
		}
		return
	case "doctor":
		if err := writeDoctorReport(os.Stdout, cfg); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	case "trust":
		if len(os.Args) < 3 || os.Args[2] == "list" {
			writeTrustList(os.Stdout, cfg)
			return
		}
		if os.Args[2] != "revoke" || len(os.Args) != 4 {
			fmt.Fprintln(os.Stderr, "Usage: slicer-bridge trust list | trust revoke <origin>")
			os.Exit(1)
		}
		if !revokeTrustedOrigin(&cfg, os.Args[3]) {
			fmt.Fprintln(os.Stderr, "Trusted origin was not found.")
			os.Exit(1)
		}
		if err := saveConfig(cfg, cfgDir); err != nil {
			fmt.Fprintf(os.Stderr, "Could not save trust revocation: %v\n", err)
			os.Exit(1)
		}
		fmt.Fprintln(os.Stdout, "Trusted origin revoked.")
		return
	}

	if err := handleProtocol(arg, cfg); err != nil {
		log.Printf("error: %v", err)
	}
}

func printUsage() {
	fmt.Println("Usage:")
	fmt.Println("  slicer-bridge --install")
	fmt.Println("  slicer-bridge --uninstall (macOS)")
	fmt.Println("  slicer-bridge --version")
	fmt.Println("  slicer-bridge list")
	fmt.Println("  slicer-bridge doctor")
	fmt.Println("  slicer-bridge trust list")
	fmt.Println("  slicer-bridge trust revoke <origin>")
	fmt.Println("  slicer-bridge <makersvault-slicer://open?...>")
	fmt.Println("  slicer-bridge <makersvault-engrave://open?...>")
	fmt.Println("  slicer-bridge <makersvault-open://open?...>")
}

func handleProtocol(raw string, cfg Config) error {
	request, err := parseProtocolRequest(raw)
	if err != nil {
		return err
	}
	log.Printf("open request tool=%s app=%s origin=%s filename=%s", request.Tool, request.AppID, request.Origin, request.Filename)

	adapter, err := resolveAdapter(request.AppID, request.Tool, cfg)
	if err != nil {
		return err
	}
	if adapter.Command == "" {
		return fmt.Errorf("configured %s application is unavailable: %s", request.Tool, request.AppID)
	}
	if request.Tool == "open" && !adapterAllows(adapter.Manifest, request.ContentRole, request.Filename) {
		return fmt.Errorf("adapter %s does not allow the requested file role or type", request.AppID)
	}
	request.Adapter = adapter.Manifest

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
	log.Printf("launch tool=%s adapter=%s", request.Tool, adapter.Manifest.ID)
	return launchCommand(adapter.Command, adapter.Args, targetPath)
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

func loadConfig() (Config, string, error) {
	cfgDir := configDir()
	cfgPath := filepath.Join(cfgDir, "config.json")
	cfg := Config{
		Slicers:   map[string]SlicerConfig{},
		Engravers: map[string]SlicerConfig{},
		Adapters:  map[string]CustomAdapterConfig{},
	}
	data, err := os.ReadFile(cfgPath)
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, cfgDir, nil
		}
		return Config{}, cfgDir, errors.New("bridge config could not be read")
	}
	cfg, err = decodeConfig(data)
	if err != nil {
		return Config{}, cfgDir, err
	}
	return cfg, cfgDir, nil
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

func launchCommand(cmd string, args []string, filePath string) error {
	allArgs, err := expandFileArgument(args, filePath)
	if err != nil {
		return fmt.Errorf("invalid adapter arguments: %w", err)
	}
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
