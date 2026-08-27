//go:build darwin

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

	bundlePath := macBundlePath(home)
	contentsPath := filepath.Join(bundlePath, "Contents")
	targetPath := filepath.Join(contentsPath, "MacOS", "makersvault-slicer")
	if !samePath(exePath, targetPath) {
		if err := copyFile(exePath, targetPath, 0755); err != nil {
			return "", fmt.Errorf("copy binary: %w", err)
		}
	} else if err := os.Chmod(targetPath, 0755); err != nil {
		return "", fmt.Errorf("set permissions: %w", err)
	}
	if err := os.WriteFile(filepath.Join(contentsPath, "Info.plist"), []byte(macBundleInfoPlist()), 0644); err != nil {
		return "", fmt.Errorf("write application metadata: %w", err)
	}
	if err := exec.Command("open", "-Ra", bundlePath).Run(); err != nil {
		return "", fmt.Errorf("register protocol handlers: %w", err)
	}
	return targetPath, nil
}

func uninstallSelf() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return "", fmt.Errorf("resolve home dir: %w", err)
	}
	bundlePath := macBundlePath(home)
	info, err := os.Stat(bundlePath)
	if err != nil {
		if os.IsNotExist(err) {
			return "", fmt.Errorf("MakerVault Bridge is not installed at %s", bundlePath)
		}
		return "", fmt.Errorf("inspect installed application: %w", err)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("installed application path is not a bundle directory")
	}
	lsregister := "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
	if err := exec.Command(lsregister, "-u", bundlePath).Run(); err != nil {
		return "", fmt.Errorf("unregister protocol handlers: %w", err)
	}
	if err := os.RemoveAll(bundlePath); err != nil {
		return "", fmt.Errorf("remove application bundle: %w", err)
	}
	return bundlePath, nil
}
