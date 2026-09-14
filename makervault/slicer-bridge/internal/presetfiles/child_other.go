//go:build (!linux && !windows) || (!amd64 && !arm64)

package presetfiles

import "context"

// Even the older explicit Darwin experiment does not opt into location scans.
func (d *directory) child(ctx context.Context, name string) (*directory, error) {
	return nil, Code("source_platform_unsupported")
}
