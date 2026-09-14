//go:build linux && (amd64 || arm64)

package presetui

import (
	"os"
	"strconv"
	"syscall"
	"unsafe"
)

const linuxOPath = 0x200000

func trustedSystemStat(s *syscall.Stat_t, directory bool) bool {
	kind := uint32(syscall.S_IFREG)
	if directory {
		kind = syscall.S_IFDIR
	}
	return s.Uid == 0 && s.Mode&syscall.S_IFMT == kind && s.Mode&0022 == 0 && s.Mode&06000 == 0 && (directory || s.Mode&0111 != 0)
}

// Fixed root-owned /usr/bin ancestry, no symlink following, regular ELF only.
// O_PATH classifies before opening file contents; exec uses the held object, not
// another lookup of its name. This is not OS package/library/mount attestation.
func openSystemTool(name string) (*os.File, error) {
	if name != "gio" && name != "zenity" {
		return nil, Code("ui_unavailable")
	}
	return openSystemELF([]string{"usr", "bin", name})
}

func openSystemELF(parts []string) (*os.File, error) {
	root, err := syscall.Open("/", linuxOPath|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, Code("ui_unavailable")
	}
	held := []int{root}
	defer func() {
		for _, fd := range held {
			syscall.Close(fd)
		}
	}()
	var before syscall.Stat_t
	if syscall.Fstat(root, &before) != nil || !trustedSystemStat(&before, true) {
		return nil, Code("ui_unavailable")
	}
	fd := root
	for i, part := range parts {
		if part == "" || part == "." || part == ".." {
			return nil, Code("ui_unavailable")
		}
		for _, c := range part {
			if c == '/' || c == 0 {
				return nil, Code("ui_unavailable")
			}
		}
		fd, err = syscall.Openat(fd, part, linuxOPath|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		if err != nil {
			return nil, Code("ui_unavailable")
		}
		held = append(held, fd)
		if syscall.Fstat(fd, &before) != nil || !trustedSystemStat(&before, i < len(parts)-1) {
			return nil, Code("ui_unavailable")
		}
	}
	if len(parts) == 0 {
		return nil, Code("ui_unavailable")
	}
	file, err := os.Open("/proc/self/fd/" + strconv.Itoa(fd))
	if err != nil {
		return nil, Code("ui_unavailable")
	}
	reject := func() (*os.File, error) { file.Close(); return nil, Code("ui_unavailable") }
	var after syscall.Stat_t
	if syscall.Fstat(int(file.Fd()), &after) != nil || before.Dev != after.Dev || before.Ino != after.Ino || !trustedSystemStat(&after, false) {
		return reject()
	}
	// Reject capability-bearing programs too; unknown xattr failures fail closed.
	attribute := append([]byte("security.capability"), 0)
	_, _, errno := syscall.Syscall6(syscall.SYS_FGETXATTR, file.Fd(), uintptr(unsafe.Pointer(&attribute[0])), 0, 0, 0, 0)
	if errno != syscall.ENODATA && errno != syscall.ENOTSUP {
		return reject()
	}
	var magic [4]byte
	if _, err = file.ReadAt(magic[:], 0); err != nil || magic != [4]byte{0x7f, 'E', 'L', 'F'} {
		return reject()
	}
	return file, nil
}

func nativeAction(req request) (string, error) {
	command, err := linuxCommand(req)
	if err != nil {
		return "", err
	}
	environment, err := linuxEnvironment(os.Getenv)
	if err != nil {
		return "", err
	}
	file, err := openSystemTool(command.name)
	if err != nil {
		return "", err
	}
	defer file.Close()
	return "", execSystemTool(file, command.args, environment, req.Operation == "browser")
}

func execSystemTool(file *os.File, args, environment []string, quiet bool) error {
	// Only called inside the single-use worker. No new child/process group; the
	// parent continues supervising this same PID through native-tool replacement.
	if os.Chdir("/") != nil {
		return Code("ui_unavailable")
	}
	if quiet {
		// GIO may launch a long-lived browser inheriting its standard streams. Never
		// give that browser the worker's private pipes or wait for browser EOF. Native
		// browser diagnostics are discarded; only GIO's exit status signals success.
		fd, err := syscall.Open("/dev/null", syscall.O_RDWR|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		if err != nil {
			return Code("ui_unavailable")
		}
		var stat syscall.Stat_t
		if syscall.Fstat(fd, &stat) != nil || stat.Mode&syscall.S_IFMT != syscall.S_IFCHR || stat.Rdev != 0x103 {
			syscall.Close(fd)
			return Code("ui_unavailable")
		}
		for _, target := range []int{0, 1, 2} {
			if syscall.Dup3(fd, target, 0) != nil {
				os.Exit(2)
			}
		}
		syscall.Close(fd)
	}
	_ = syscall.Exec("/proc/self/fd/"+strconv.Itoa(int(file.Fd())), args, environment)
	if quiet {
		os.Exit(2)
	} // stdout is now /dev/null: never report false empty success
	return Code("ui_unavailable")
}
