//go:build darwin && (amd64 || arm64) && makersvault_darwin_reader_experiment

package presetfiles

import (
	"context"
	"os"
	"runtime"
	"strings"
	"syscall"
	"unsafe"
)

// EXPERIMENT ONLY. Default builds keep the unsupported backend. These held-parent
// opens validate identity before consuming data, but a post-open check CANNOT
// undo a raced-in FIFO/device open or mount/recall side effect. Native experiments
// document that gap; do not enable this tag in release builds. No O_PATH parity.
// Pinned Apple definitions/source rationale are in DARWIN_EXPERIMENT.md.
const (
	darwinSYSOpenat    = 463
	darwinSYSFstatat64 = 470
	darwinNoFollowAny  = 0x20000000
	darwinAtNoFollow   = 0x20
	darwinLocal        = 0x1000
	darwinDataless     = 0x40000000
)

type directory struct{ file *os.File }

func darwinError(err syscall.Errno) error {
	switch err {
	case syscall.ENOSYS, syscall.EINVAL:
		return Code("source_boundary_unavailable")
	case syscall.ELOOP, syscall.EXDEV:
		return Code("source_unsafe")
	default:
		return Code("source_unavailable")
	}
}

func darwinStatAt(dir *os.File, name string) (syscall.Stat_t, error) {
	var stat syscall.Stat_t
	path, err := syscall.BytePtrFromString(name)
	if err != nil {
		return stat, Code("source_path_invalid")
	}
	_, _, errno := syscall.Syscall6(darwinSYSFstatat64, dir.Fd(), uintptr(unsafe.Pointer(path)),
		uintptr(unsafe.Pointer(&stat)), darwinAtNoFollow, 0, 0)
	runtime.KeepAlive(dir)
	if errno != 0 {
		return stat, darwinError(errno)
	}
	return stat, nil
}

// Callers supply one validated basename, never an absolute/profile include path.
func darwinOpenAt(dir *os.File, name string, flags int) (*os.File, error) {
	path, err := syscall.BytePtrFromString(name)
	if err != nil {
		return nil, Code("source_path_invalid")
	}
	flags |= syscall.O_RDONLY | syscall.O_CLOEXEC | syscall.O_NOFOLLOW | darwinNoFollowAny |
		syscall.O_NONBLOCK | syscall.O_NOCTTY
	fd, _, errno := syscall.Syscall6(darwinSYSOpenat, dir.Fd(), uintptr(unsafe.Pointer(path)), uintptr(flags), 0, 0, 0)
	runtime.KeepAlive(dir)
	if errno != 0 {
		return nil, darwinError(errno)
	}
	return os.NewFile(fd, "profile-handle"), nil
}

func darwinFilesystem(file *os.File) (syscall.Fsid, error) {
	var stat syscall.Statfs_t
	if syscall.Fstatfs(int(file.Fd()), &stat) != nil {
		return stat.Fsid, Code("source_unavailable")
	}
	var name []byte
	for _, value := range stat.Fstypename {
		if value == 0 {
			break
		}
		name = append(name, byte(value))
	}
	if stat.Flags&darwinLocal == 0 || string(name) != "apfs" {
		return stat.Fsid, Code("source_filesystem_unsupported")
	}
	return stat.Fsid, nil
}

func darwinSame(a, b syscall.Stat_t) bool {
	return a.Dev == b.Dev && a.Ino == b.Ino && a.Mode == b.Mode && a.Nlink == b.Nlink &&
		a.Size == b.Size && a.Mtimespec == b.Mtimespec && a.Ctimespec == b.Ctimespec &&
		a.Birthtimespec == b.Birthtimespec && a.Flags == b.Flags && a.Gen == b.Gen
}

func darwinKind(stat syscall.Stat_t, directory bool) bool {
	kind := uint16(syscall.S_IFREG)
	if directory {
		kind = syscall.S_IFDIR
	}
	return stat.Mode&syscall.S_IFMT == kind && stat.Flags&darwinDataless == 0 &&
		(directory || stat.Nlink == 1)
}

func openDirectory(ctx context.Context, path string) (*directory, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if !rootName(path) {
		return nil, Code("source_path_invalid")
	}
	parts := strings.Split(strings.TrimPrefix(path, "/"), "/")
	for _, part := range parts {
		if !componentName(part) {
			return nil, Code("source_path_invalid")
		}
	}
	// The literal filesystem root has no traversable components. Applying
	// NOFOLLOW_ANY to this zero-component anchor returns EINVAL on the test Mac.
	// Every caller-derived component below still requires both no-follow flags.
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, Code("source_unavailable")
	}
	current := os.NewFile(uintptr(fd), "profile-anchor")
	defer func() {
		if current != nil {
			current.Close()
		}
	}()
	if _, err := darwinFilesystem(current); err != nil {
		return nil, err
	}
	for _, part := range parts {
		if err := check(ctx); err != nil {
			return nil, err
		}
		before, err := darwinStatAt(current, part)
		if err != nil {
			return nil, err
		}
		if !darwinKind(before, true) {
			return nil, Code("source_unsafe")
		}
		next, err := darwinOpenAt(current, part, syscall.O_DIRECTORY)
		if err != nil {
			return nil, err
		}
		var after syscall.Stat_t
		statErr := syscall.Fstat(int(next.Fd()), &after)
		if statErr != nil || !darwinSame(before, after) {
			next.Close()
			return nil, Code("source_changed")
		}
		current.Close()
		current = next
		// Local APFS transitions on the way to the selected root include macOS's
		// system/data volume layout. No claim of pre-open mount confinement.
		if _, err := darwinFilesystem(current); err != nil {
			return nil, err
		}
	}
	if err := check(ctx); err != nil {
		return nil, err
	}
	result := &directory{file: current}
	current = nil
	return result, nil
}

func (d *directory) close() { d.file.Close() }

func (d *directory) metadata(ctx context.Context, name string) (syscall.Stat_t, error) {
	var stat syscall.Stat_t
	if err := check(ctx); err != nil {
		return stat, err
	}
	if !fileName(name) {
		return stat, Code("source_path_invalid")
	}
	stat, err := darwinStatAt(d.file, name)
	if err != nil {
		return stat, err
	}
	var parent syscall.Stat_t
	if syscall.Fstat(int(d.file.Fd()), &parent) != nil {
		return stat, Code("source_unavailable")
	}
	if !darwinKind(stat, false) || stat.Dev != parent.Dev {
		return stat, Code("source_unsafe")
	}
	return stat, nil
}

func (d *directory) inspect(ctx context.Context, name string) error {
	_, err := d.metadata(ctx, name)
	return err
}

func (d *directory) open(ctx context.Context, name string) (*os.File, error) {
	before, err := d.metadata(ctx, name)
	if err != nil {
		return nil, err
	}
	file, err := darwinOpenAt(d.file, name, 0)
	if err != nil {
		return nil, err
	}
	var after syscall.Stat_t
	if syscall.Fstat(int(file.Fd()), &after) != nil || !darwinKind(after, false) || !darwinSame(before, after) {
		file.Close()
		return nil, Code("source_changed")
	}
	parentFS, parentErr := darwinFilesystem(d.file)
	fileFS, fileErr := darwinFilesystem(file)
	if parentErr != nil || fileErr != nil || parentFS != fileFS {
		file.Close()
		return nil, Code("source_filesystem_unsupported")
	}
	if err := check(ctx); err != nil {
		file.Close()
		return nil, err
	}
	return file, nil
}

func sameChange(before, after os.FileInfo) bool {
	a, aOK := before.Sys().(*syscall.Stat_t)
	b, bOK := after.Sys().(*syscall.Stat_t)
	return aOK && bOK && darwinSame(*a, *b)
}
