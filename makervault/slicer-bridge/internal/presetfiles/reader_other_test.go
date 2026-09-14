//go:build (!linux && !windows && !darwin) || (!amd64 && !arm64) || (darwin && !makersvault_darwin_reader_experiment)

package presetfiles

import (
	"context"
	"testing"
)

func TestNativeBackendFailsClosed(t *testing.T) {
	if dir, err := openDirectory(context.Background(), t.TempDir()); dir != nil || err != Code("source_platform_unsupported") {
		t.Fatalf("unimplemented native boundary did not fail closed: %v %v", dir, err)
	}
	if manifest, err := ReadBambuManifest(context.Background(), t.TempDir()); manifest != nil || err != Code("source_platform_unsupported") {
		t.Fatalf("manifest bypassed unsupported native boundary: %v %v", manifest, err)
	}
}
