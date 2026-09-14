//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"syscall"
)

// Child traversal remains BELOW the selected root: NO_XDEV must never be lost
// by resolving an absolute joined child as a separately approved root.
func (d *directory) child(ctx context.Context, name string) (*directory, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if !componentName(name) {
		return nil, Code("source_path_invalid")
	}
	held, err := openAt(d.file, name, oPath|syscall.O_DIRECTORY, true)
	if err != nil {
		return nil, err
	}
	defer held.Close()
	if !localFilesystem(held) {
		return nil, Code("source_filesystem_unsupported")
	}
	readable, err := openAt(held, ".", syscall.O_RDONLY|syscall.O_DIRECTORY, true)
	if err != nil {
		return nil, err
	}
	if err := check(ctx); err != nil {
		readable.Close()
		return nil, err
	}
	return &directory{file: readable}, nil
}
