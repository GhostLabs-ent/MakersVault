//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestSavedUserBoundaryRejectsLinksAndFIFO(t *testing.T) {
	for _, kind := range []string{"symlink", "hardlink", "fifo"} {
		t.Run(kind, func(t *testing.T) {
			root := discoveryFixture(t)
			target := filepath.Join(root, "user/private-account/machine/local-file.json")
			moved := filepath.Join(root, "private-fixture.json")
			if err := os.Rename(target, moved); err != nil {
				t.Fatal(err)
			}
			var err error
			switch kind {
			case "symlink":
				err = os.Symlink(moved, target)
			case "hardlink":
				err = os.Link(moved, target)
			case "fifo":
				err = syscall.Mkfifo(target, 0600)
			}
			if err != nil {
				t.Fatal(err)
			}
			if discovery, err := DiscoverBambu(context.Background(), root, "private-account"); discovery != nil || err != Code("source_unsafe") {
				t.Fatal("unsafe user body opened", err)
			}
		})
	}
}
