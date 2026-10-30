//go:build !windows && !linux

package main

import "fmt"

func installSelf() (string, error) {
	return "", fmt.Errorf("unsupported OS for installer")
}
