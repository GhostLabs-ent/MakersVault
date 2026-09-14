//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestDiscoveryRejectsUnsafeBodiesWithoutFollowingIncludes(t *testing.T) {
	for _, kind := range []string{"symlink", "hardlink", "fifo"} {
		t.Run(kind, func(t *testing.T) {
			root := discoveryFixture(t)
			target := filepath.Join(root, "system/BBL/machine/not-the-name.json")
			moved := filepath.Join(root, "held-fixture.json")
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
			if got, err := DiscoverBambu(context.Background(), root, ""); got != nil || err != Code("source_unsafe") {
				t.Fatal("unsafe body accepted", err)
			}
		})
	}
	root := discoveryFixture(t)
	target := filepath.Join(root, "system/BBL/machine/include-trap.json")
	if err := os.Rename(target, filepath.Join(root, "moved-trap")); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(target, 0600); err != nil {
		t.Fatal(err)
	}
	if got, err := DiscoverBambu(context.Background(), root, ""); err != nil || len(got.Selections) != 1 {
		t.Fatal("include was opened", err)
	}
}

func TestDiscoveryHeldAncestryAndFinalChangeCheck(t *testing.T) {
	root := discoveryFixture(t)
	ctx := context.Background()
	catalog := printerpreset.NewBambu(ctx)
	session, err := openBambuLocation(ctx, root, "", catalog)
	if err != nil {
		t.Fatal(err)
	}
	defer session.close()
	if err := os.Rename(filepath.Join(root, "system"), filepath.Join(root, "moved-system")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, "system"), 0700); err != nil {
		t.Fatal(err)
	}
	source := printerpreset.Source{Namespace: discoveryNamespace, Kind: printerpreset.System}
	if err := loadBoundFile(ctx, session.systemMachine, "base.json", "Base", source, catalog); err != nil {
		t.Fatal("held source lost", err)
	}
	if err := session.check(ctx); err != Code("source_changed") {
		t.Fatal("changed ancestry published", err)
	}
}

func TestDiscoveryNestedMountAndPermissions(t *testing.T) {
	if _, err := os.Stat("/location-mount/system/BBL.json"); err != nil {
		t.Skip("requires isolated mount fixture")
	}
	if got, err := DiscoverBambu(context.Background(), "/location-mount", ""); got != nil || err != Code("source_unsafe") {
		t.Fatal("mount boundary lost", err)
	}
	if os.Geteuid() == 0 {
		t.Skip("requires unprivileged verification")
	}
	root := discoveryFixture(t)
	blocked := filepath.Join(root, "user/private-account")
	if err := os.Chmod(blocked, 0000); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(blocked, 0700)
	if got, err := DiscoverBambu(context.Background(), root, "private-account"); got != nil || err != Code("source_unavailable") {
		t.Fatal("selected account ignored", err)
	}
	if got, err := DiscoverBambu(context.Background(), root, ""); err != nil || got.UserIncluded {
		t.Fatal("unselected account read", err)
	}
}
