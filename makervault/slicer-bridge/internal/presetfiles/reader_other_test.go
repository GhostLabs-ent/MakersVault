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
}
