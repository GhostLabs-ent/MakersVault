//go:build !windows && !linux && !darwin

package main

import "fmt"

func installSelf() (string, error) {
	return "", fmt.Errorf("unsupported OS for installer")
}

func uninstallSelf() (string, error) {
	return "", fmt.Errorf("unsupported OS for uninstaller")
}
