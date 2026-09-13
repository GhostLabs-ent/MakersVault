//go:build !linux || (!amd64 && !arm64)

package presetfiles

import (
	"context"
	"os"
)

// Deliberately fail closed until the native backend is implemented and tested.
// Cross-building this stub is not Windows/macOS filesystem qualification.
type directory struct{ file *os.File }

func openDirectory(context.Context, string) (*directory, error) {
	return nil, Code("source_platform_unsupported")
}
func (d *directory) close() {}
func (d *directory) inspect(context.Context, string) error {
	return Code("source_platform_unsupported")
}
func (d *directory) open(context.Context, string) (*os.File, error) {
	return nil, Code("source_platform_unsupported")
}
func sameChange(os.FileInfo, os.FileInfo) bool { return false }
