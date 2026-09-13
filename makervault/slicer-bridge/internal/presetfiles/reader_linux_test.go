//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"io"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/printerpreset"
)

func writeFixture(t *testing.T, root, name, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, name), []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
}

func fixtureInput(t *testing.T) Input {
	t.Helper()
	root := t.TempDir()
	names := []string{"child.json", "base.json", "common.json"}
	for _, name := range names {
		data, err := os.ReadFile(filepath.Join("../printerpreset/testdata", name))
		if err != nil {
			t.Fatal(err)
		}
		writeFixture(t, root, name, string(data))
	}
	return Input{Root: root, Files: names, Source: printerpreset.Source{Namespace: "local-selection", Kind: printerpreset.System}}
}

func TestExplicitBambuReadAndResolve(t *testing.T) {
	input := fixtureInput(t)
	before := map[string][]byte{}
	for _, name := range input.Files {
		before[name], _ = os.ReadFile(filepath.Join(input.Root, name))
	}
	catalog, err := LoadBambu(context.Background(), []Input{input})
	if err != nil {
		t.Fatal(err)
	}
	// The I/O deadline's cancellation must not invalidate the returned catalog.
	candidate, err := catalog.Resolve(input.Source.Namespace, printerpreset.System, "Fixture P1S 0.4")
	if err != nil {
		t.Fatal(err)
	}
	if !candidate.Complete() || *candidate.Nozzle != 0.4 || candidate.Bed[2].X != 256 {
		t.Fatalf("unexpected projection: %+v", candidate)
	}
	for _, name := range input.Files {
		after, err := os.ReadFile(filepath.Join(input.Root, name))
		if err != nil || string(before[name]) != string(after) {
			t.Fatal("source mutated")
		}
	}
}

func TestPairedSystemAndUserRoots(t *testing.T) {
	system := fixtureInput(t)
	user := Input{Root: t.TempDir(), Files: []string{"user.json"},
		Source: printerpreset.Source{Namespace: system.Source.Namespace, Kind: printerpreset.User}}
	writeFixture(t, user.Root, "user.json", `{"type":"machine","name":"Fixture user","from":"user","instantiation":"true","inherits":"Fixture P1S 0.4","nozzle_diameter":["0.6"]}`)
	catalog, err := LoadBambu(context.Background(), []Input{user, system})
	if err != nil {
		t.Fatal(err)
	}
	candidate, err := catalog.Resolve(user.Source.Namespace, printerpreset.User, "Fixture user")
	if err != nil || !candidate.Complete() || *candidate.Nozzle != 0.6 || candidate.Provenance.Bed != "inherited" {
		t.Fatalf("paired roots failed: %+v %v", candidate, err)
	}
}

func TestDirectListingNoRecursiveScan(t *testing.T) {
	root := t.TempDir()
	writeFixture(t, root, "z.JSON", "not parsed by listing")
	writeFixture(t, root, "a.json", "not parsed by listing")
	writeFixture(t, root, "BambuStudio.conf", "fake credential")
	if err := os.Mkdir(filepath.Join(root, "user"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("/never-read", filepath.Join(root, "unrelated-link")); err != nil {
		t.Fatal(err)
	}
	names, err := ListJSON(context.Background(), root)
	if err != nil || !reflect.DeepEqual(names, []string{"a.json", "z.JSON"}) {
		t.Fatalf("%v %v", names, err)
	}
}

func TestUnsafeJSONObjectsNeverRead(t *testing.T) {
	for _, kind := range []string{"outside-symlink", "inside-symlink", "hardlink", "fifo", "socket", "directory"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			target := filepath.Join(root, "profile.json")
			switch kind {
			case "outside-symlink":
				outside := filepath.Join(t.TempDir(), "secret")
				writeFixture(t, filepath.Dir(outside), "secret", "PRIVATE")
				if err := os.Symlink(outside, target); err != nil {
					t.Fatal(err)
				}
			case "inside-symlink":
				writeFixture(t, root, "data", "PRIVATE")
				if err := os.Symlink("data", target); err != nil {
					t.Fatal(err)
				}
			case "hardlink":
				outside := filepath.Join(t.TempDir(), "secret")
				writeFixture(t, filepath.Dir(outside), "secret", "PRIVATE")
				if err := os.Link(outside, target); err != nil {
					t.Fatal(err)
				}
			case "fifo":
				if err := syscall.Mkfifo(target, 0600); err != nil {
					t.Fatal(err)
				}
			case "socket":
				listener, err := net.Listen("unix", target)
				if err != nil {
					t.Fatal(err)
				}
				defer listener.Close()
			case "directory":
				if err := os.Mkdir(target, 0700); err != nil {
					t.Fatal(err)
				}
			}
			if kind == "outside-symlink" || kind == "inside-symlink" || kind == "hardlink" {
				// Negative control: an ordinary path reader reaches the synthetic
				// private marker. The confined reader below must reject this input.
				data, err := os.ReadFile(target)
				if err != nil || string(data) != "PRIVATE" {
					t.Fatal("invalid escape fixture")
				}
			}
			start := time.Now()
			names, err := ListJSON(context.Background(), root)
			if names != nil || err != Code("source_unsafe") {
				t.Fatalf("%v %v", names, err)
			}
			input := Input{Root: root, Files: []string{"profile.json"}, Source: printerpreset.Source{Namespace: "local", Kind: printerpreset.System}}
			if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err != Code("source_unsafe") {
				t.Fatalf("%v %v", c, err)
			}
			if time.Since(start) > 3*time.Second {
				t.Fatal("special file blocked the reader")
			}
		})
	}
}

func TestRootAndAncestorSymlinksRejected(t *testing.T) {
	base, target := t.TempDir(), t.TempDir()
	if err := os.Mkdir(filepath.Join(target, "machine"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(base, "link")); err != nil {
		t.Fatal(err)
	}
	for _, root := range []string{filepath.Join(base, "link"), filepath.Join(base, "link", "machine")} {
		if names, err := ListJSON(context.Background(), root); err == nil || names != nil {
			t.Fatal("symlink root accepted")
		}
	}
	for _, root := range []string{"/", "//tmp/root", "/tmp/../root", "/tmp/root/", "relative", "https://host/root", "/tmp/\nsecret"} {
		if names, err := ListJSON(context.Background(), root); names != nil || err != Code("source_path_invalid") {
			t.Fatalf("%q %v", root, err)
		}
	}
}

func TestFilesystemPolicyRejectsPseudoMount(t *testing.T) {
	if names, err := ListJSON(context.Background(), "/proc"); names != nil || err != Code("source_filesystem_unsupported") {
		t.Fatalf("%v %v", names, err)
	}
}

func TestConfinedOpenRejectsMountCrossing(t *testing.T) {
	// No mount or privilege change: every Linux container already has procfs.
	fd, err := os.Open("/")
	if err != nil {
		t.Fatal(err)
	}
	defer fd.Close()
	file, err := openAt(fd, "proc", oPath|syscall.O_DIRECTORY, true)
	if file != nil {
		file.Close()
		t.Fatal("mount crossing accepted")
	}
	if err != Code("source_unsafe") {
		t.Fatal(err)
	}
}

func TestSameDeviceBindMountRejected(t *testing.T) {
	// The evidence driver mounts the synthetic fixture directory here, with a
	// second same-filesystem file bind mount over child.json. No test mounts or
	// changes privileges. Outside that isolated driver this case is unqualified.
	if _, err := os.Stat("/mount-fixture/child.json"); err != nil {
		t.Skip("requires explicit disposable-container fixture mounts")
	}
	dir, err := openDirectory(context.Background(), "/mount-fixture")
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	var rootStat, childStat syscall.Stat_t
	if err := syscall.Fstat(int(dir.file.Fd()), &rootStat); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Stat("/mount-fixture/child.json", &childStat); err != nil {
		t.Fatal(err)
	}
	if rootStat.Dev != childStat.Dev {
		t.Fatal("fixture does not exercise same-device mount")
	}
	if file, err := dir.open(context.Background(), "child.json"); file != nil || err != Code("source_unsafe") {
		if file != nil {
			file.Close()
		}
		t.Fatalf("same-device bind accepted: %v", err)
	}
	if names, err := ListJSON(context.Background(), "/mount-fixture"); names != nil || err != Code("source_unsafe") {
		t.Fatalf("partial bind-mounted directory listing: %v %v", names, err)
	}
}

func TestReadPermissions(t *testing.T) {
	input := fixtureInput(t)
	blocked := filepath.Join(input.Root, input.Files[0])
	if err := os.Chmod(blocked, 0000); err != nil {
		t.Fatal(err)
	}
	if os.Geteuid() == 0 {
		t.Skip("permission rejection requires the unprivileged verification run")
	}
	if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err != Code("source_unavailable") {
		t.Fatalf("unreadable file accepted: %v %v", c, err)
	}
	if err := os.Chmod(input.Root, 0000); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(input.Root, 0700)
	if names, err := ListJSON(context.Background(), input.Root); names != nil || err != Code("source_unavailable") {
		t.Fatalf("unreadable directory accepted: %v %v", names, err)
	}
}

func TestAmbiguousAndOversizedSelections(t *testing.T) {
	input := fixtureInput(t)
	for _, names := range [][]string{{"a.json", "A.JSON"}, {"../a.json"}, {"a.json", "a.json"}, {"C:secret.json"}} {
		input.Files = names
		if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err == nil {
			t.Fatal("unsafe selection accepted")
		}
	}
	input.Files = make([]string, printerpreset.MaxFiles+1)
	for i := range input.Files {
		input.Files[i] = "profile-" + strconv.Itoa(i) + ".json"
	}
	if c, err := LoadBambu(context.Background(), []Input{input}); c != nil || err != Code("source_file_limit_exceeded") {
		t.Fatalf("%v %v", c, err)
	}
	input = fixtureInput(t)
	duplicate := input
	if c, err := LoadBambu(context.Background(), []Input{input, duplicate}); c != nil || err != Code("source_selection_invalid") {
		t.Fatalf("%v %v", c, err)
	}
	duplicate.Source.Kind = printerpreset.User
	duplicate.Source.Namespace = "other-account"
	if c, err := LoadBambu(context.Background(), []Input{input, duplicate}); c != nil || err != Code("source_selection_invalid") {
		t.Fatalf("%v %v", c, err)
	}
}

func TestListingBudgetCountsIgnoredEntries(t *testing.T) {
	root := t.TempDir()
	for i := 0; i <= MaxEntries; i++ {
		writeFixture(t, root, "ignored-"+strconv.Itoa(i), "")
	}
	if names, err := ListJSON(context.Background(), root); names != nil || err != Code("source_entry_limit_exceeded") {
		t.Fatalf("%v %v", names, err)
	}
}

func TestListingRejectsCaseCollisions(t *testing.T) {
	root := t.TempDir()
	writeFixture(t, root, "printer.json", "")
	writeFixture(t, root, "PRINTER.JSON", "")
	if names, err := ListJSON(context.Background(), root); names != nil || err != Code("source_ambiguous_filename") {
		t.Fatalf("%v %v", names, err)
	}
}

func TestNoPartialCatalogOnReadOrParseFailure(t *testing.T) {
	for _, failure := range []string{"missing", "malformed", "oversized"} {
		t.Run(failure, func(t *testing.T) {
			input := fixtureInput(t)
			input.Files = append(input.Files, "bad.json")
			switch failure {
			case "malformed":
				writeFixture(t, input.Root, "bad.json", `{"private":"not valid`)
			case "oversized":
				file, err := os.Create(filepath.Join(input.Root, "bad.json"))
				if err != nil {
					t.Fatal(err)
				}
				if err := file.Truncate(printerpreset.MaxFileBytes + 1); err != nil {
					t.Fatal(err)
				}
				file.Close()
			}
			c, err := LoadBambu(context.Background(), []Input{input})
			if c != nil || err == nil {
				t.Fatal("partial catalog escaped")
			}
			if strings.Contains(err.Error(), input.Root) || strings.Contains(err.Error(), "private") {
				t.Fatal("path/content leaked")
			}
		})
	}
}

func TestHeldRootDoesNotFollowReplacement(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "selected")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	writeFixture(t, root, "a.json", "SELECTED")
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	if err := os.Rename(root, filepath.Join(base, "old")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	writeFixture(t, root, "a.json", "REPLACEMENT")
	file, err := dir.open(context.Background(), "a.json")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	data, err := io.ReadAll(file)
	if err != nil || string(data) != "SELECTED" {
		t.Fatal("re-resolved root pathname")
	}
}

func TestReplacementRaceNeverReadsSymlinkTarget(t *testing.T) {
	root, outside := t.TempDir(), t.TempDir()
	writeFixture(t, outside, "private", "PRIVATE")
	writeFixture(t, root, "a.json", "SELECTED")
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 300; i++ {
			// All mutations stay inside this test's temporary root.
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
	for i := 0; i < 500; i++ {
		file, err := dir.open(context.Background(), "a.json")
		if err != nil {
			continue
		}
		data, readErr := io.ReadAll(file)
		file.Close()
		if readErr != nil || string(data) != "SELECTED" {
			t.Errorf("unexpected raced content: %q %v", data, readErr)
		}
	}
	wg.Wait()
}

func TestChangeDetectionAndCancelledRead(t *testing.T) {
	root := t.TempDir()
	writeFixture(t, root, "a.json", "BEFORE")
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	file, err := dir.open(context.Background(), "a.json")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	before, err := file.Stat()
	if err != nil {
		t.Fatal(err)
	}
	writeFixture(t, root, "a.json", "AFTER!")
	if err := os.Chtimes(filepath.Join(root, "a.json"), before.ModTime(), before.ModTime()); err != nil {
		t.Fatal(err)
	}
	if unchanged(file, before) {
		t.Fatal("ctime change ignored after mtime reset")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := (contextReader{ctx, file}).Read(make([]byte, 1)); err != Code("source_cancelled") {
		t.Fatal(err)
	}
	if _, err := dir.open(ctx, "a.json"); err != Code("source_cancelled") {
		t.Fatal(err)
	}
}

func TestBoundaryErrorMappingHasNoPathOrFallback(t *testing.T) {
	for _, errno := range []syscall.Errno{syscall.ENOSYS, syscall.EINVAL, syscall.E2BIG} {
		if pathError(errno) != Code("source_boundary_unavailable") {
			t.Fatal("weaker fallback category")
		}
	}
	for _, errno := range []syscall.Errno{syscall.ELOOP, syscall.EXDEV} {
		if pathError(errno) != Code("source_unsafe") {
			t.Fatal("unsafe path category")
		}
	}
	if pathError(syscall.EAGAIN) != Code("source_changed") || pathError(syscall.EACCES) != Code("source_unavailable") {
		t.Fatal("unexpected failure category")
	}
}
