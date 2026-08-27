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
	targetPath := filepath.Join(installDir, "makersvault-slicer")
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
	desktopFile := filepath.Join(desktopDir, "makersvault-slicer.desktop")
	desktop := fmt.Sprintf(
		"[Desktop Entry]\nName=MakerVault Bridge\nExec=%s %%u\nType=Application\nTerminal=false\nMimeType=x-scheme-handler/makersvault-slicer;x-scheme-handler/makersvault-engrave;x-scheme-handler/makersvault-open;\n",
		targetPath,
	)
	if err := os.WriteFile(desktopFile, []byte(desktop), 0644); err != nil {
		return "", fmt.Errorf("write desktop entry: %w", err)
	}

	if xdgMime, err := exec.LookPath("xdg-mime"); err == nil {
		for _, scheme := range registeredProtocolSchemes {
			_ = exec.Command(xdgMime, "default", "makersvault-slicer.desktop", "x-scheme-handler/"+scheme).Run()
		}
	}

	return targetPath, nil
}

func uninstallSelf() (string, error) {
	return "", fmt.Errorf("automatic uninstall is currently supported only on macOS")
}
