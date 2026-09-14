//go:build (!linux && !windows) || (!amd64 && !arm64)

package presetfiles

import "context"

func nativeLocationHints(context.Context) (LocationHints, error) {
	return LocationHints{}, Code("source_platform_unsupported")
}
