//go:build darwin && (amd64 || arm64) && makersvault_darwin_reader_experiment

package presetfiles

import (
	"context"
	"io"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"syscall"
	"testing"
	"unsafe"

	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestDarwinExperimentalNativePrimitives(t *testing.T) {
	for _, probe := range []struct {
		label string
		flags int
	}{{"root-base", syscall.O_RDONLY | syscall.O_DIRECTORY | syscall.O_CLOEXEC | syscall.O_NOFOLLOW},
		{"root-nofollow-any", syscall.O_RDONLY | syscall.O_DIRECTORY | syscall.O_CLOEXEC | syscall.O_NOFOLLOW | darwinNoFollowAny}} {
		fd, err := syscall.Open("/", probe.flags, 0)
		t.Logf("primitive=%s errno=%v", probe.label, err)
		if err == nil {
			syscall.Close(fd)
		}
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		t.Fatalf("anchor-open errno=%v", err)
	}
	defer syscall.Close(fd)
	var fs syscall.Statfs_t
	if err := syscall.Fstatfs(fd, &fs); err != nil {
		t.Fatalf("anchor-statfs errno=%v", err)
	}
	name, _ := syscall.BytePtrFromString("private")
	var stat syscall.Stat_t
	_, _, errno := syscall.Syscall6(darwinSYSFstatat64, uintptr(fd), uintptr(unsafe.Pointer(name)), uintptr(unsafe.Pointer(&stat)), darwinAtNoFollow, 0, 0)
	t.Logf("primitive=fstatat64 errno=%d mode=%o dev=%d struct-size=%d", errno, stat.Mode, stat.Dev, unsafe.Sizeof(stat))
	flags := syscall.O_RDONLY | syscall.O_DIRECTORY | syscall.O_CLOEXEC | syscall.O_NOFOLLOW | darwinNoFollowAny | syscall.O_NONBLOCK | syscall.O_NOCTTY
	child, _, errno := syscall.Syscall6(darwinSYSOpenat, uintptr(fd), uintptr(unsafe.Pointer(name)), uintptr(flags), 0, 0, 0)
	t.Logf("primitive=openat errno=%d", errno)
	if errno == 0 {
		syscall.Close(int(child))
	}
}

func darwinWrite(t *testing.T, root, name, data string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, name), []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
}

func darwinFixture(t *testing.T) Input {
	t.Helper()
	input := Input{Root: t.TempDir(), Files: []string{"base.json", "child.json", "common.json"},
		Source: printerpreset.Source{Namespace: "fixture-local-only", Kind: printerpreset.System}}
	for _, name := range input.Files {
		data, err := os.ReadFile(filepath.Join("../printerpreset/testdata", name))
		if err != nil {
			t.Fatal(err)
		}
		darwinWrite(t, input.Root, name, string(data))
	}
	return input
}

func TestDarwinExperimentalListLoadAndSourcePreservation(t *testing.T) {
	input := darwinFixture(t)
	before := map[string][]byte{}
	for _, name := range input.Files {
		before[name], _ = os.ReadFile(filepath.Join(input.Root, name))
	}
	names, err := ListJSON(context.Background(), input.Root)
	if err != nil || !reflect.DeepEqual(names, input.Files) {
		t.Fatalf("list: %v %v", names, err)
	}
	catalog, err := LoadBambu(context.Background(), []Input{input})
	if err != nil {
		t.Fatal(err)
	}
	candidate, err := catalog.Resolve(input.Source.Namespace, printerpreset.System, "Fixture P1S 0.4")
	if err != nil || !candidate.Complete() || *candidate.Nozzle != 0.4 || candidate.Bed[2].X != 256 {
		t.Fatalf("projection: %v %v", candidate, err)
	}
	for name, bytes := range before {
		after, err := os.ReadFile(filepath.Join(input.Root, name))
		if err != nil || string(bytes) != string(after) {
			t.Fatal("source changed")
		}
	}
}

func TestDarwinExperimentalStatABIAndReadOnlyHandle(t *testing.T) {
	root := t.TempDir()
	darwinWrite(t, root, "a.json", "SELECTED")
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	before, err := darwinStatAt(dir.file, "a.json")
	if err != nil {
		t.Fatal(err)
	}
	file, err := dir.open(context.Background(), "a.json")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	var after syscall.Stat_t
	if syscall.Fstat(int(file.Fd()), &after) != nil || !darwinSame(before, after) || after.Size != 8 {
		t.Fatal("fstatat64/Fstat ABI or identity mismatch")
	}
	if _, err := file.WriteString("MUTATION"); err == nil {
		t.Fatal("writable source handle")
	}
	flags, _, errno := syscall.Syscall(syscall.SYS_FCNTL, file.Fd(), syscall.F_GETFD, 0)
	if errno != 0 || flags&syscall.FD_CLOEXEC == 0 {
		t.Fatal("descriptor can survive exec")
	}
}

func TestDarwinExperimentalStaticUnsafeEntries(t *testing.T) {
	for _, kind := range []string{"symlink", "hardlink", "fifo", "socket", "directory"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			if kind == "socket" {
				// Darwin Unix-domain socket paths have a small fixed size.
				short, err := os.MkdirTemp(os.Getenv("TMPDIR"), "socket-")
				if err != nil {
					t.Fatal(err)
				}
				root = short
				t.Cleanup(func() { os.RemoveAll(short) })
			}
			target := filepath.Join(root, "a.json")
			var err error
			switch kind {
			case "symlink", "hardlink":
				outside := t.TempDir()
				darwinWrite(t, outside, "private", "PRIVATE")
				if kind == "symlink" {
					err = os.Symlink(filepath.Join(outside, "private"), target)
				} else {
					err = os.Link(filepath.Join(outside, "private"), target)
				}
			case "fifo":
				err = syscall.Mkfifo(target, 0600)
			case "socket":
				var listener net.Listener
				listener, err = net.Listen("unix", target)
				if err == nil {
					defer listener.Close()
				}
			case "directory":
				err = os.Mkdir(target, 0700)
			}
			if err != nil {
				t.Fatal(err)
			}
			if names, err := ListJSON(context.Background(), root); names != nil || err != Code("source_unsafe") {
				t.Fatalf("static unsafe entry accepted: %v %v", names, err)
			}
			input := Input{Root: root, Files: []string{"a.json"}, Source: printerpreset.Source{Namespace: "fixture", Kind: printerpreset.System}}
			if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err != Code("source_unsafe") {
				t.Fatalf("unsafe catalog: %v %v", c, err)
			}
		})
	}
}

func TestDarwinExperimentalRootSymlinksAndCaseCollision(t *testing.T) {
	root, outside := t.TempDir(), t.TempDir()
	if err := os.Symlink(outside, filepath.Join(root, "link")); err != nil {
		t.Fatal(err)
	}
	for _, target := range []string{filepath.Join(root, "link"), filepath.Join(root, "link", "nested")} {
		if names, err := ListJSON(context.Background(), target); names != nil || err != Code("source_unsafe") {
			t.Fatalf("root symlink accepted: %v %v", names, err)
		}
	}
	input := darwinFixture(t)
	input.Files = []string{"a.json", "A.JSON"}
	if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err != Code("source_ambiguous_filename") {
		t.Fatal("case collision accepted")
	}
}

func TestDarwinExperimentalHeldRootAndChangeDetection(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "selected")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	darwinWrite(t, root, "a.json", "SELECTED")
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	old := filepath.Join(base, "renamed")
	if err := os.Rename(root, old); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	darwinWrite(t, root, "a.json", "REPLACED")
	file, err := dir.open(context.Background(), "a.json")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	bytes, err := io.ReadAll(file)
	if err != nil || string(bytes) != "SELECTED" {
		t.Fatal("root pathname re-resolved")
	}
	before, err := file.Stat()
	if err != nil {
		t.Fatal(err)
	}
	darwinWrite(t, old, "a.json", "MODIFIED")
	if err := os.Chtimes(filepath.Join(old, "a.json"), before.ModTime(), before.ModTime()); err != nil {
		t.Fatal(err)
	}
	if unchanged(file, before) {
		t.Fatal("change hidden by restored mtime")
	}
}

func TestDarwinExperimentalPermissionsAndAtomicFailure(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Fatal("requires unprivileged native verification")
	}
	input := darwinFixture(t)
	file := filepath.Join(input.Root, "child.json")
	if err := os.Chmod(file, 0000); err != nil {
		t.Fatal(err)
	}
	if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err != Code("source_unavailable") {
		t.Fatalf("unreadable source: %v %v", c, err)
	}
	if err := os.Chmod(file, 0600); err != nil {
		t.Fatal(err)
	}
	input.Files = append(input.Files, "missing.json")
	if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err == nil || strings.Contains(err.Error(), input.Root) {
		t.Fatal("partial catalog or path escaped")
	}
}

func TestDarwinExperimentalSymlinkReplacementRace(t *testing.T) {
	root, outside := t.TempDir(), t.TempDir()
	darwinWrite(t, root, "a.json", "SELECTED")
	darwinWrite(t, outside, "private", "PRIVATE")
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 200; i++ {
			if err := os.Symlink(filepath.Join(outside, "private"), filepath.Join(root, "next")); err != nil {
				t.Error(err)
				return
			}
			if err := os.Rename(filepath.Join(root, "next"), filepath.Join(root, "a.json")); err != nil {
				t.Error(err)
				return
			}
			if err := os.WriteFile(filepath.Join(root, "next"), []byte("SELECTED"), 0600); err != nil {
				t.Error(err)
				return
			}
			if err := os.Rename(filepath.Join(root, "next"), filepath.Join(root, "a.json")); err != nil {
				t.Error(err)
				return
			}
		}
	}()
	for i := 0; i < 400; i++ {
		file, err := dir.open(context.Background(), "a.json")
		if err != nil {
			continue
		}
		bytes, err := io.ReadAll(file)
		file.Close()
		if err != nil || string(bytes) != "SELECTED" {
			t.Error("symlink race exposed outside bytes")
		}
	}
	wg.Wait()
}

// A passing counterexample is a FAILED safety property, not release approval.
// No data is sent: only our own FIFO endpoints are opened/closed in a temp root.
func TestDarwinCounterexampleEventOnlyOpensFIFO(t *testing.T) {
	root := t.TempDir()
	name := filepath.Join(root, "fifo")
	if err := syscall.Mkfifo(name, 0600); err != nil {
		t.Fatal(err)
	}
	if fd, err := syscall.Open(name, syscall.O_WRONLY|syscall.O_NONBLOCK, 0); err != syscall.ENXIO {
		if err == nil {
			syscall.Close(fd)
		}
		t.Fatal("invalid no-reader control")
	}
	reader, err := syscall.Open(name, syscall.O_EVTONLY|syscall.O_NONBLOCK|syscall.O_NOFOLLOW, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.Close(reader)
	writer, err := syscall.Open(name, syscall.O_WRONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		t.Fatal("counterexample not reproduced; investigate native semantics")
	}
	syscall.Close(writer)
	t.Log("safety-property=metadata-only-event-handle FAILED counterexample=FIFO-reader-endpoint-opened")
}

func TestDarwinCounterexamplePostOpenCheckCannotUndoFIFOOpen(t *testing.T) {
	root := t.TempDir()
	darwinWrite(t, root, "a.json", "SELECTED")
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	before, err := dir.metadata(context.Background(), "a.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(root, "a.json")); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(filepath.Join(root, "a.json"), 0600); err != nil {
		t.Fatal(err)
	}
	// Force the replacement precisely between metadata and native open.
	file, err := darwinOpenAt(dir.file, "a.json", 0)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	var after syscall.Stat_t
	if syscall.Fstat(int(file.Fd()), &after) != nil || darwinSame(before, after) || darwinKind(after, false) {
		t.Fatal("post-open validation failed to detect replacement")
	}
	writer, err := syscall.Open(filepath.Join(root, "a.json"), syscall.O_WRONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		t.Fatal("counterexample not reproduced")
	}
	syscall.Close(writer)
	t.Log("safety-property=no-special-file-open-before-kind-validation FAILED counterexample=postcheck-detects-too-late")
}
