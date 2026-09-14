//go:build windows && (amd64 || arm64)

package presetfiles

import (
	"context"
	"syscall"
)

func (d *directory) accountEntry(ctx context.Context, name string) (bool, error) {
	if err := check(ctx); err != nil {
		return false, err
	}
	if _, err := validateHandle(d.file, true, d.volume); err != nil {
		return false, err
	}
	file, err := openRelativeTyped(d.file, name, false, false)
	if err != nil {
		return false, err
	}
	defer file.Close()
	var info syscall.ByHandleFileInformation
	if syscall.GetFileInformationByHandle(syscall.Handle(file.Fd()), &info) != nil {
		return false, Code("source_unavailable")
	}
	isDirectory := info.FileAttributes&syscall.FILE_ATTRIBUTE_DIRECTORY != 0
	if _, err := validateHandle(file, isDirectory, d.volume); err != nil {
		return false, err
	}
	return isDirectory, check(ctx)
}
