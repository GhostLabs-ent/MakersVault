//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestManifestRejectsLinksAndFIFO(t *testing.T) {
	for _, kind := range []string{"symlink", "hardlink", "fifo"} {
		t.Run(kind, func(t *testing.T) {
			root, outside := t.TempDir(), t.TempDir()
			writeFixture(t, outside, "private.json", manifestFixture)
			target := filepath.Join(root, "BBL.json")
			var err error
			switch kind {
			case "symlink":
				err = os.Symlink(filepath.Join(outside, "private.json"), target)
			case "hardlink":
				err = os.Link(filepath.Join(outside, "private.json"), target)
			case "fifo":
				err = syscall.Mkfifo(target, 0600)
			}
			if err != nil {
				t.Fatal(err)
			}
			if m, err := ReadBambuManifest(context.Background(), root); m != nil || err != Code("source_unsafe") {
				t.Fatalf("unsafe manifest: %v %v", m, err)
			}
		})
	}
}
