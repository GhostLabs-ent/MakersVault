//go:build windows && (amd64 || arm64)

package presetfiles

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"unsafe"

	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestWindowsNTStructureLayout(t *testing.T) {
	if unsafe.Sizeof(ntUnicodeString{}) != 16 || unsafe.Sizeof(ntObjectAttributes{}) != 48 || unsafe.Sizeof(ntIOStatus{}) != 16 {
		t.Fatal("NT ABI layout mismatch")
	}
}

func TestWindowsNativeListLoadAndReadOnly(t *testing.T) {
	root := t.TempDir()
	names := []string{"base.json", "common.json", "child.json"}
	for _, name := range names {
		data, err := os.ReadFile(filepath.Join("../printerpreset/testdata", name))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, name), data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	listed, err := ListJSON(context.Background(), root)
	if err != nil || !reflect.DeepEqual(listed, []string{"base.json", "child.json", "common.json"}) {
		t.Fatalf("%v %v", listed, err)
	}
	catalog, err := LoadBambu(context.Background(), []Input{{Root: root, Files: names,
		Source: printerpreset.Source{Namespace: "local-fixture", Kind: printerpreset.System}}})
	if err != nil {
		t.Fatal(err)
	}
	candidate, err := catalog.Resolve("local-fixture", printerpreset.System, "Fixture P1S 0.4")
	if err != nil || !candidate.Complete() {
		t.Fatalf("%v %v", candidate, err)
	}
	for _, name := range names {
		before, _ := os.ReadFile(filepath.Join("../printerpreset/testdata", name))
		after, err := os.ReadFile(filepath.Join(root, name))
		if err != nil || string(before) != string(after) {
			t.Fatal("source changed")
		}
	}
}

func TestWindowsNativeHardlinkAndDirectoryRejected(t *testing.T) {
	for _, kind := range []string{"hardlink", "directory"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			target := filepath.Join(root, "a.json")
			if kind == "directory" {
				if err := os.Mkdir(target, 0700); err != nil {
					t.Fatal(err)
				}
			} else {
				source := filepath.Join(t.TempDir(), "source")
				if err := os.WriteFile(source, []byte("SYNTHETIC_PRIVATE"), 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.Link(source, target); err != nil {
					t.Fatal(err)
				}
			}
			if names, err := ListJSON(context.Background(), root); names != nil || err == nil {
				t.Fatal("unsafe object accepted")
			}
		})
	}
}

func TestWindowsNativeHeldFileDeniesReplacement(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "a.json")
	if err := os.WriteFile(path, []byte("SELECTED"), 0600); err != nil {
		t.Fatal(err)
	}
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
	if err := os.Rename(path, filepath.Join(root, "other.json")); err == nil {
		t.Fatal("held file was renamed")
	}
	if err := os.WriteFile(path, []byte("REPLACEMENT"), 0600); err == nil {
		t.Fatal("held file was overwritten")
	}
	data, err := io.ReadAll(file)
	if err != nil || string(data) != "SELECTED" {
		t.Fatal("held file changed")
	}
}

func TestWindowsNativeSymlinkRejection(t *testing.T) {
	root, target := t.TempDir(), t.TempDir()
	if err := os.WriteFile(filepath.Join(target, "a.json"), []byte("SYNTHETIC_PRIVATE"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(root, "linked")); err != nil {
		t.Skipf("native symlink fixture unavailable; reparse qualification remains open: %T", err)
	}
	if names, err := ListJSON(context.Background(), filepath.Join(root, "linked")); names != nil || err == nil {
		t.Fatal("reparse root accepted")
	}
}
