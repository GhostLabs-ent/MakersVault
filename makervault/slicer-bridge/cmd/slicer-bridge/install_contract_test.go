package main

import (
	"strings"
	"testing"
)

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
