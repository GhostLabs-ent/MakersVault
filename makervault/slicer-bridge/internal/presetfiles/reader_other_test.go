//go:build (!linux && !windows) || (!amd64 && !arm64)

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
