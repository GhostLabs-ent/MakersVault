//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"unsafe"
)

// Linux UAPI, common to the supported amd64/arm64 ABIs. Unsupported kernels or
// seccomp policies fail closed; there is no path-based or weaker syscall fallback.
// See README for pinned kernel definitions and the O_PATH/proc-fd rationale.
const (
	sysOpenat2          = 437
	oPath               = 0x200000
	resolveNoXdev       = 0x01
	resolveNoMagicLinks = 0x02
	resolveNoSymlinks   = 0x04
	resolveBeneath      = 0x08
)

type openHow struct{ flags, mode, resolve uint64 }
type directory struct{ file *os.File }

func openAt(dir *os.File, name string, flags int, noMount bool) (*os.File, error) {
	path, err := syscall.BytePtrFromString(name)
	if err != nil {
		return nil, Code("source_path_invalid")
	}
	how := openHow{flags: uint64(flags | syscall.O_CLOEXEC | syscall.O_NOFOLLOW),
		resolve: resolveBeneath | resolveNoSymlinks | resolveNoMagicLinks}
	if noMount {
		how.resolve |= resolveNoXdev
	}
	fd, _, errno := syscall.Syscall6(sysOpenat2, dir.Fd(), uintptr(unsafe.Pointer(path)),
		uintptr(unsafe.Pointer(&how)), unsafe.Sizeof(how), 0, 0)
	runtime.KeepAlive(dir)
	if errno != 0 {
		return nil, pathError(errno)
	}
	return os.NewFile(fd, "profile-handle"), nil
}

func pathError(err syscall.Errno) error {
	switch err {
	case syscall.ENOSYS, syscall.EINVAL, syscall.E2BIG:
		return Code("source_boundary_unavailable")
	case syscall.ELOOP, syscall.EXDEV:
		return Code("source_unsafe")
	case syscall.EAGAIN:
		return Code("source_changed")
	default:
		return Code("source_unavailable")
	}
}

// Allow only these local filesystem families. Unknown/FUSE/network/pseudo roots
// are unsupported, not silently retried through ordinary os.Open. This is a
// conservative policy, not a claim about a block device's physical backing.
func localFilesystem(file *os.File) bool {
	var stat syscall.Statfs_t
	if syscall.Fstatfs(int(file.Fd()), &stat) != nil {
		return false
	}
	switch uint64(stat.Type) {
	case 0xef53, 0x9123683e, 0x58465342, 0x01021994, 0x794c7630:
		return true // ext2/3/4, btrfs, xfs, tmpfs, overlay
	}
	return false
}

func openDirectory(ctx context.Context, path string) (*directory, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if !rootName(path) {
		return nil, Code("source_path_invalid")
	}
	fd, err := syscall.Open("/", oPath|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, Code("source_unavailable")
	}
	current := os.NewFile(uintptr(fd), "profile-anchor")
	defer func() { current.Close() }()
	if !localFilesystem(current) {
		return nil, Code("source_filesystem_unsupported")
	}
	// Open each ancestor as O_PATH: do not trigger a terminal automount or follow
	// symlinks. Permit ordinary local mount points on the way TO the chosen root;
	// below that exact root, NO_XDEV rejects even same-device bind mounts.
	for _, part := range strings.Split(strings.TrimPrefix(path, "/"), "/") {
		if err := check(ctx); err != nil {
			return nil, err
		}
		next, err := openAt(current, part, oPath|syscall.O_DIRECTORY, false)
		if err != nil {
			return nil, err
		}
		current.Close()
		current = next
		if !localFilesystem(current) {
			return nil, Code("source_filesystem_unsupported")
		}
	}
	// Convert the held O_PATH directory into a readable descriptor relative to
	// itself, never by re-resolving the caller's absolute path.
	readable, err := openAt(current, ".", syscall.O_RDONLY|syscall.O_DIRECTORY, true)
	if err != nil {
		return nil, err
	}
	if err := check(ctx); err != nil {
		readable.Close()
		return nil, err
	}
	return &directory{file: readable}, nil
}

func (d *directory) close() { d.file.Close() }

func (d *directory) pathHandle(ctx context.Context, name string) (*os.File, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if !fileName(name) {
		return nil, Code("source_path_invalid")
	}
	file, err := openAt(d.file, name, oPath, true)
	if err != nil {
		return nil, err
	}
	var stat syscall.Stat_t
	if syscall.Fstat(int(file.Fd()), &stat) != nil {
		file.Close()
		return nil, Code("source_unavailable")
	}
	// O_PATH can return a final symlink handle with O_NOFOLLOW. Reject it and all
	// other special files WITHOUT opening them for data (including FIFOs/devices).
	if stat.Mode&syscall.S_IFMT != syscall.S_IFREG || stat.Nlink != 1 {
		file.Close()
		return nil, Code("source_unsafe")
	}
	if !localFilesystem(file) {
		file.Close()
		return nil, Code("source_filesystem_unsupported")
	}
	return file, nil
}

func (d *directory) inspect(ctx context.Context, name string) error {
	file, err := d.pathHandle(ctx, name)
	if err != nil {
		return err
	}
	file.Close()
	return check(ctx)
}

func (d *directory) open(ctx context.Context, name string) (*os.File, error) {
	handle, err := d.pathHandle(ctx, name)
	if err != nil {
		return nil, err
	}
	defer handle.Close()
	before, err := handle.Stat()
	if err != nil {
		return nil, Code("source_unavailable")
	}
	// This fixed proc-fd path refers to our still-held, already-validated regular
	// inode, NOT a profile-supplied path. It avoids the stat/open replacement race.
	// A missing/restricted procfs fails closed. No shell, URL or arbitrary include.
	file, err := os.OpenFile("/proc/self/fd/"+strconv.FormatUint(uint64(handle.Fd()), 10), os.O_RDONLY|syscall.O_NONBLOCK|syscall.O_NOCTTY, 0)
	if err != nil {
		return nil, Code("source_unavailable")
	}
	if !unchanged(file, before) {
		file.Close()
		return nil, Code("source_changed")
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
	return aOK && bOK && a.Ctim == b.Ctim && a.Nlink == b.Nlink
}
