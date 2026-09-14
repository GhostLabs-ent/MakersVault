//go:build (linux || windows) && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestManifestReadDoesNotVisitReferences(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "BBL.json")
	if err := os.WriteFile(path, []byte(manifestFixture), 0600); err != nil {
		t.Fatal(err)
	}
	// No machine directories or referenced files exist. Only BBL.json is needed.
	m, err := ReadBambuManifest(context.Background(), root)
	if err != nil || m == nil || len(m.Machines) != 3 {
		t.Fatalf("%v %v", m, err)
	}
	after, err := os.ReadFile(path)
	if err != nil || string(after) != manifestFixture {
		t.Fatal("manifest mutated")
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 1 {
		t.Fatal("reader created files")
	}
}

func TestManifestReadFailureIsAtomic(t *testing.T) {
	for _, failure := range []string{"missing", "malformed", "oversized", "directory"} {
		t.Run(failure, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, "BBL.json")
			switch failure {
			case "malformed":
				if err := os.WriteFile(path, []byte(manifestFixture+"{PRIVATE"), 0600); err != nil {
					t.Fatal(err)
				}
			case "oversized":
				file, err := os.Create(path)
				if err != nil {
					t.Fatal(err)
				}
				err = file.Truncate(printerpreset.MaxFileBytes + 1)
				file.Close()
				if err != nil {
					t.Fatal(err)
				}
			case "directory":
				if err := os.Mkdir(path, 0700); err != nil {
					t.Fatal(err)
				}
			}
			if m, err := ReadBambuManifest(context.Background(), root); m != nil || err == nil {
				t.Fatalf("partial index: %v %v", m, err)
			}
		})
	}
	if m, err := ReadBambuManifest(context.Background(), "relative"); m != nil || err != Code("source_path_invalid") {
		t.Fatal(err)
	}
}
