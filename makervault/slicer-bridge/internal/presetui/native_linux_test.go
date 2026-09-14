//go:build linux && (amd64 || arm64)

package presetui

import (
	"context"
	"os"
	"strconv"
	"syscall"
	"testing"
)

func init() { nativeFixture = linuxExecFixture }
func linuxExecFixture(mode string) {
	switch mode {
	case "linux-system-exec":
		file, err := openSystemELF([]string{"usr", "bin", "true"})
		if err != nil {
			os.Exit(61)
		}
		_ = execSystemTool(file, []string{"true"}, nil, false)
		os.Exit(62)
	case "linux-quiet-exec":
		executable, err := os.Executable()
		if err != nil {
			os.Exit(63)
		}
		file, err := os.Open(executable)
		if err != nil {
			os.Exit(64)
		}
		_ = execSystemTool(file, []string{"fixture", "--fixture-linux-quiet-target"}, []string{"FIXTURE_PID=" + strconv.Itoa(os.Getpid()), "GORACE=atexit_sleep_ms=0"}, true)
		os.Exit(65)
	case "linux-quiet-target":
		if os.Getenv("FIXTURE_PID") != strconv.Itoa(os.Getpid()) {
			os.Exit(66)
		}
		for _, fd := range []int{0, 1, 2} {
			var s syscall.Stat_t
			if syscall.Fstat(fd, &s) != nil || s.Mode&syscall.S_IFMT != syscall.S_IFCHR || s.Rdev != 0x103 {
				os.Exit(67)
			}
		}
		_, _ = os.Stdout.WriteString("PRIVATE_DIAGNOSTIC")
		_, _ = os.Stderr.WriteString("PRIVATE_DIAGNOSTIC")
		os.Exit(0)
	case "linux-quiet-exec-failure":
		file, err := os.Open("/dev/null")
		if err != nil {
			os.Exit(68)
		}
		_ = execSystemTool(file, []string{"fixture"}, nil, true)
		os.Exit(0) // must not return/signal false success
	}
}
func TestLinuxSystemExecutableTrust(t *testing.T) {
	file, err := openSystemELF([]string{"usr", "bin", "true"})
	if err != nil {
		t.Fatal("root-owned system ELF refused")
	}
	file.Close()
	for _, name := range []string{"sh", "../gio", "/usr/bin/gio", "private"} {
		if file, err := openSystemTool(name); err != Code("ui_unavailable") || file != nil {
			t.Fatal("unlisted helper accepted")
		}
	}
	for _, parts := range [][]string{nil, {"tmp", "untrusted"}, {"usr", "bin", "sh"}, {"usr", "bin", "missing-maker-fixture"}, {"usr", "bin", "."}, {"usr", "bin", "../gio"}} {
		if file, err := openSystemELF(parts); err != Code("ui_unavailable") || file != nil {
			t.Fatal("unsafe executable path accepted")
		}
	}
	safe := syscall.Stat_t{Uid: 0, Mode: syscall.S_IFREG | 0755}
	if !trustedSystemStat(&safe, false) {
		t.Fatal("regular root ELF mode refused")
	}
	for _, mode := range []uint32{syscall.S_IFREG | 0777, syscall.S_IFREG | 06755, syscall.S_IFREG | 0644, syscall.S_IFLNK | 0777, syscall.S_IFIFO | 0755, syscall.S_IFCHR | 0755} {
		s := safe
		s.Mode = mode
		if trustedSystemStat(&s, false) {
			t.Fatal("unsafe inode accepted")
		}
	}
	safe.Uid = 1000
	if trustedSystemStat(&safe, false) {
		t.Fatal("user-owned tool accepted")
	}
}
func TestLinuxExecKeepsPIDAndSeparatesBrowserStreams(t *testing.T) {
	for _, mode := range []string{"linux-system-exec", "linux-quiet-exec"} {
		data, err := supervise(context.Background(), fixtureCommand(t, mode), nil)
		if err != nil || len(data) != 0 {
			t.Fatal("same-PID native exec or private stream isolation failed")
		}
		waitIdle(t)
	}
	data, err := supervise(context.Background(), fixtureCommand(t, "linux-quiet-exec-failure"), nil)
	if err != Code("ui_failed") || data != nil {
		t.Fatal("quiet exec failure became false success")
	}
	waitIdle(t)
}
