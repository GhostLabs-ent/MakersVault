//go:build linux

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func installSelf() (string, error) {
	exePath, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("resolve executable: %w", err)
	}
	exePath, err = filepath.EvalSymlinks(exePath)
	if err != nil {
		return "", fmt.Errorf("resolve executable: %w", err)
	}

	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return "", fmt.Errorf("resolve home dir: %w", err)
	}
	installDir := filepath.Join(home, ".local", "bin")
	targetPath := filepath.Join(installDir, "curiarium-slicer")
	if !samePath(exePath, targetPath) {
		if err := copyFile(exePath, targetPath, 0755); err != nil {
			return "", fmt.Errorf("copy binary: %w", err)
		}
	} else if err := os.Chmod(targetPath, 0755); err != nil {
		return "", fmt.Errorf("set permissions: %w", err)
	}

	desktopDir := filepath.Join(home, ".local", "share", "applications")
	if err := os.MkdirAll(desktopDir, 0755); err != nil {
		return "", fmt.Errorf("create desktop dir: %w", err)
	}
	desktopFile := filepath.Join(desktopDir, "curiarium-slicer.desktop")
	desktop := fmt.Sprintf(
		"[Desktop Entry]\nName=Curiarium Bridge\nExec=%s %%u\nType=Application\nTerminal=false\nMimeType=x-scheme-handler/curiarium-slicer;x-scheme-handler/curiarium-engrave;\n",
		targetPath,
	)
	if err := os.WriteFile(desktopFile, []byte(desktop), 0644); err != nil {
		return "", fmt.Errorf("write desktop entry: %w", err)
	}

	if xdgMime, err := exec.LookPath("xdg-mime"); err == nil {
		_ = exec.Command(xdgMime, "default", "curiarium-slicer.desktop", "x-scheme-handler/curiarium-slicer").Run()
		_ = exec.Command(xdgMime, "default", "curiarium-slicer.desktop", "x-scheme-handler/curiarium-engrave").Run()
	}

	return targetPath, nil
}
