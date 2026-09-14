//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
)

func nativeLocationHints(ctx context.Context) (LocationHints, error) {
	return linuxLocationHints(ctx, os.Getenv)
}

// Injected lookup in tests; no passwd/NSS lookup, config reads or directory walk.
// Invalid nonempty XDG does not silently fall back to another profile namespace.
func linuxLocationHints(ctx context.Context, getenv func(string) string) (LocationHints, error) {
	if err := check(ctx); err != nil {
		return LocationHints{}, err
	}
	hints := LocationHints{Platform: "linux", ConfigHome: getenv("XDG_CONFIG_HOME")}
	if hints.ConfigHome == "" {
		hints.UserHome = getenv("HOME")
	}
	return hints, check(ctx)
}
