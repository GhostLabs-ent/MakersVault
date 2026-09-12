package main

import (
	"reflect"
	"strings"
	"testing"
)

func TestPairingBrowserCommandPlatforms(t *testing.T) {
	// Only inspect command construction; never launch a browser on the test host.
	target := "http://127.0.0.1:32123/confirm/0123456789abcdef"
	for _, test := range []struct {
		platform string
		args     []string
	}{
		{"windows", []string{"cmd", "/c", "start", "", target}},
		{"linux", []string{"xdg-open", target}},
		{"darwin", []string{"/usr/bin/open", target}},
	} {
		t.Run(test.platform, func(t *testing.T) {
			command, err := pairingBrowserCommand(test.platform, target)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(command.Args, test.args) {
				t.Fatalf("arguments = %q, want %q", command.Args, test.args)
			}
		})
	}
}

func TestPairingBrowserCommandKeepsUnixTargetLiteral(t *testing.T) {
	for _, platform := range []string{"linux", "darwin"} {
		target := `http://127.0.0.1:1234/confirm/test?literal="space here"&value=$test;no-command`
		command, err := pairingBrowserCommand(platform, target)
		if err != nil {
			t.Fatal(err)
		}
		if len(command.Args) != 2 || command.Args[1] != target {
			t.Fatalf("%s split or expanded target: %q", platform, command.Args)
		}
	}
}

func TestPairingBrowserCommandUnsupportedPlatform(t *testing.T) {
	command, err := pairingBrowserCommand("unsupported", "http://127.0.0.1:1/confirm/test")
	if command != nil || err == nil || !strings.Contains(err.Error(), "unsupported OS") {
		t.Fatalf("unsupported platform must fail closed: %v, %v", command, err)
	}
}
