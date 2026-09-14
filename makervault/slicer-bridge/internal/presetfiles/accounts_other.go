//go:build (!linux && !windows) || (!amd64 && !arm64)

package presetfiles

import "context"

func (d *directory) accountEntry(context.Context, string) (bool, error) {
	return false, Code("source_platform_unsupported")
}
