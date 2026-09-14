//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"syscall"
)

func (d *directory) accountEntry(ctx context.Context, name string) (bool, error) {
	if err := check(ctx); err != nil {
		return false, err
	}
	if !componentName(name) {
		return false, Code("source_path_invalid")
	}
	file, err := openAt(d.file, name, oPath, true)
	if err != nil {
		return false, err
	}
	defer file.Close()
	var stat syscall.Stat_t
	if syscall.Fstat(int(file.Fd()), &stat) != nil {
		return false, Code("source_unavailable")
	}
	kind := stat.Mode & syscall.S_IFMT
	if kind != syscall.S_IFDIR && (kind != syscall.S_IFREG || stat.Nlink != 1) {
		return false, Code("source_unsafe")
	}
	if !localFilesystem(file) {
		return false, Code("source_filesystem_unsupported")
	}
	return kind == syscall.S_IFDIR, check(ctx)
}
