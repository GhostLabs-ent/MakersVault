//go:build windows

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

	baseDir := os.Getenv("LOCALAPPDATA")
	if baseDir == "" {
		if cfgDir, err := os.UserConfigDir(); err == nil && cfgDir != "" {
			baseDir = cfgDir
		}
	}
	if baseDir == "" {
		return "", fmt.Errorf("LOCALAPPDATA is not set")
	}
	targetDir := filepath.Join(baseDir, "MakersVault", "SlicerBridge")
	targetExe := filepath.Join(targetDir, "makersvault-slicer.exe")
	if !samePath(exePath, targetExe) {
		if err := copyFile(exePath, targetExe, 0755); err != nil {
			return "", fmt.Errorf("copy binary: %w", err)
		}
	}

	for _, scheme := range registeredProtocolSchemes {
		if err := registerProtocol(scheme, "MakerVault Bridge", targetExe); err != nil {
			return "", err
		}
	}

	return targetExe, nil
}

func uninstallSelf() (string, error) {
	return "", fmt.Errorf("automatic uninstall is currently supported only on macOS")
}

func registerProtocol(scheme, label, targetExe string) error {
	root := fmt.Sprintf(`HKCU\Software\Classes\%s`, scheme)
	if err := regAdd(root, "/ve", "/t", "REG_SZ", "/d", "URL:"+label, "/f"); err != nil {
		return err
	}
	if err := regAdd(root, "/v", "URL Protocol", "/t", "REG_SZ", "/d", "1", "/f"); err != nil {
		return err
	}
	commandKey := root + `\shell\open\command`
	command := fmt.Sprintf("\"%s\" \"%%1\"", targetExe)
	if err := regAdd(commandKey, "/ve", "/t", "REG_SZ", "/d", command, "/f"); err != nil {
		return err
	}
	return nil
}

func regAdd(key string, args ...string) error {
	cmdArgs := append([]string{"add", key}, args...)
	cmd := exec.Command("reg", cmdArgs...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("registry update failed: %w", err)
	}
	return nil
}
