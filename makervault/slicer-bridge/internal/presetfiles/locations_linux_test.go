//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestLocationRejectsNestedLinksAndSpecialDirectories(t *testing.T) {
	for _, relative := range []string{"system", "system/BBL", "system/BBL/machine", "user", "user/chosen-account", "user/chosen-account/machine"} {
		t.Run(relative, func(t *testing.T) {
			root := locationFixture(t)
			target := filepath.Join(root, relative)
			moved := filepath.Join(root, "fixture-moved-directory")
			if err := os.Rename(target, moved); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(moved, target); err != nil {
				t.Fatal(err)
			}
			if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); result != nil || err == nil {
				t.Fatal("nested symlink followed")
			}
		})
	}
	for _, kind := range []string{"fifo", "file"} {
		t.Run(kind, func(t *testing.T) {
			root := locationFixture(t)
			target := filepath.Join(root, "system", "BBL", "machine")
			if err := os.Rename(target, filepath.Join(root, "fixture-moved-directory")); err != nil {
				t.Fatal(err)
			}
			var err error
			if kind == "fifo" {
				err = syscall.Mkfifo(target, 0600)
			} else {
				err = os.WriteFile(target, []byte("PRIVATE"), 0600)
			}
			if err != nil {
				t.Fatal(err)
			}
			if result, err := InspectBambuLocation(context.Background(), root, ""); result != nil || err == nil {
				t.Fatal("special child accepted")
			}
		})
	}
}

func TestLocationChildUsesHeldParent(t *testing.T) {
	root := locationFixture(t)
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	system, err := dir.child(context.Background(), "system")
	if err != nil {
		t.Fatal(err)
	}
	defer system.close()
	if err := os.Rename(filepath.Join(root, "system"), filepath.Join(root, "moved-system")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, "system"), 0700); err != nil {
		t.Fatal(err)
	}
	// Replacement has no BBL: this can succeed only using the held original.
	vendor, err := system.child(context.Background(), "BBL")
	if err != nil {
		t.Fatal(err)
	}
	vendor.close()
	for _, name := range []string{"..", ".", "../system", "/system", "NUL"} {
		if child, err := dir.child(context.Background(), name); child != nil || err != Code("source_path_invalid") {
			t.Fatal("unsafe child accepted")
		}
	}
}

func TestLocationRejectsSameDeviceDirectoryBind(t *testing.T) {
	if _, err := os.Stat("/location-mount/system/BBL.json"); err != nil {
		t.Skip("requires isolated same-device directory bind fixture")
	}
	var rootStat, childStat syscall.Stat_t
	if syscall.Stat("/location-mount", &rootStat) != nil || syscall.Stat("/location-mount/system", &childStat) != nil || rootStat.Dev != childStat.Dev {
		t.Fatal("not a same-device bind fixture")
	}
	// Negative control: treating the nested mount as a NEW explicit root permits
	// reading it. The anchored operation must instead retain the original boundary.
	if m, err := ReadBambuManifest(context.Background(), "/location-mount/system"); err != nil || m == nil {
		t.Fatal(err)
	}
	if result, err := InspectBambuLocation(context.Background(), "/location-mount", ""); result != nil || err != Code("source_unsafe") {
		t.Fatalf("nested mount boundary lost: %v %v", result, err)
	}
}

func TestLocationPermissionsDoNotFallBack(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("requires unprivileged verification")
	}
	root := locationFixture(t)
	blocked := filepath.Join(root, "user", "chosen-account")
	if err := os.Chmod(blocked, 0000); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(blocked, 0700)
	if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); result != nil || err != Code("source_unavailable") {
		t.Fatal("unreadable selected account ignored")
	}
	if result, err := InspectBambuLocation(context.Background(), root, ""); err != nil || result.UserIncluded {
		t.Fatal("unselected account touched")
	}
}
