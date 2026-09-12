package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestManualInstallersRegisterEverySupportedProtocol(t *testing.T) {
	for _, script := range []string{"install-linux.sh", "install-windows.ps1"} {
		t.Run(script, func(t *testing.T) {
			data, err := os.ReadFile(filepath.Join("..", "..", "scripts", script))
			if err != nil {
				t.Fatal(err)
			}
			for _, scheme := range registeredProtocolSchemes {
				registration := `Register-Protocol -Protocol "` + scheme + `"`
				if script == "install-linux.sh" {
					registration = "xdg-mime default makersvault-slicer.desktop x-scheme-handler/" + scheme
					if !strings.Contains(string(data), "x-scheme-handler/"+scheme+";") {
						t.Errorf("desktop descriptor missing %s", scheme)
					}
				}
				if !strings.Contains(string(data), registration) {
					t.Errorf("manual installer missing %s registration", scheme)
				}
			}
		})
	}
}

func TestInstallersRegisterEverySupportedProtocol(t *testing.T) {
	want := []string{slicerScheme, engraveScheme, generalScheme}
	if len(registeredProtocolSchemes) != len(want) {
		t.Fatalf("registered schemes = %v, want %v", registeredProtocolSchemes, want)
	}
	for index, scheme := range want {
		if registeredProtocolSchemes[index] != scheme {
			t.Fatalf("registered schemes = %v, want %v", registeredProtocolSchemes, want)
		}
	}
}

func TestMacBundleDeclaresEverySupportedProtocol(t *testing.T) {
	plist := macBundleInfoPlist()
	for _, scheme := range registeredProtocolSchemes {
		if !strings.Contains(plist, "<string>"+scheme+"</string>") {
			t.Fatalf("macOS bundle is missing %s", scheme)
		}
	}
}

func TestDarwinApplicationCandidatesIncludeSystemAndUserLocations(t *testing.T) {
	candidates := darwinApplicationCandidates(
		[]string{"/Applications/FreeCAD.app/Contents/MacOS/FreeCAD"},
		"/Users/maker",
	)
	want := []string{
		"/Applications/FreeCAD.app/Contents/MacOS/FreeCAD",
		"/Users/maker/Applications/FreeCAD.app/Contents/MacOS/FreeCAD",
	}
	if len(candidates) != len(want) {
		t.Fatalf("darwin candidates = %v, want %v", candidates, want)
	}
	for index := range want {
		if candidates[index] != want[index] {
			t.Fatalf("darwin candidates = %v, want %v", candidates, want)
		}
	}
}

func TestMacBundlePathIsUserLocalAndExact(t *testing.T) {
	got := macBundlePath("/Users/maker")
	want := "/Users/maker/Applications/MakerVault Bridge.app"
	if got != want {
		t.Fatalf("macOS bundle path = %q, want %q", got, want)
	}
}
