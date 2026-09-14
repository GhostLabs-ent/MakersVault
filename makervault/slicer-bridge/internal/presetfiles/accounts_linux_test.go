//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"syscall"
	"testing"
)

func TestAccountsRejectUnsafeEntriesAtomically(t *testing.T) {
	for _, kind := range []string{"link", "fifo", "hardlink", "invalid", "collision", "sidecar-collision", "user-link"} {
		t.Run(kind, func(t *testing.T) {
			root := locationFixture(t)
			user := filepath.Join(root, "user")
			var err error
			switch kind {
			case "link":
				err = os.Symlink("chosen-account", filepath.Join(user, "other"))
			case "fifo":
				err = syscall.Mkfifo(filepath.Join(user, "other"), 0600)
			case "hardlink":
				err = os.Link(filepath.Join(root, "BambuStudio.conf"), filepath.Join(user, "sidecar"))
			case "invalid":
				err = os.Mkdir(filepath.Join(user, "NUL"), 0700)
			case "collision":
				err = os.Mkdir(filepath.Join(user, "CHOSEN-ACCOUNT"), 0700)
			case "sidecar-collision":
				err = os.WriteFile(filepath.Join(user, "CHOSEN-ACCOUNT"), nil, 0600)
			case "user-link":
				if err = os.Rename(user, filepath.Join(root, "moved-user")); err == nil {
					err = os.Symlink("moved-user", user)
				}
			}
			if err != nil {
				t.Fatal(err)
			}
			if result, err := ListBambuAccounts(context.Background(), root); result != nil || err == nil {
				t.Fatal("unsafe entry ignored or partial choices returned")
			}
		})
	}
}

func TestAccountsUseHeldParentAndDetectChanges(t *testing.T) {
	root := locationFixture(t)
	dir, err := openDirectory(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	defer dir.close()
	before, err := dir.file.Stat()
	if err != nil {
		t.Fatal(err)
	}
	user, err := dir.child(context.Background(), "user")
	if err != nil {
		t.Fatal(err)
	}
	defer user.close()
	if err := os.Rename(filepath.Join(root, "user"), filepath.Join(root, "moved-user")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, "user"), 0700); err != nil {
		t.Fatal(err)
	}
	names, err := listAccounts(context.Background(), user, MaxEntries)
	if err != nil || !reflect.DeepEqual(names, []string{"chosen-account"}) || unchanged(dir.file, before) {
		t.Fatal("reopened replacement or failed to detect parent change")
	}
}

func TestAccountsPermissionsAndNoDescent(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("requires unprivileged verification")
	}
	root := locationFixture(t)
	account := filepath.Join(root, "user", "chosen-account")
	if err := os.Chmod(account, 0000); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(account, 0700)
	if result, err := ListBambuAccounts(context.Background(), root); err != nil || len(result.Names) != 1 {
		t.Fatal("enumeration descended into an account")
	}
	if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); result != nil || err != Code("source_unavailable") {
		t.Fatal("selection ignored unavailable account")
	}
	user := filepath.Join(root, "user")
	if err := os.Chmod(user, 0000); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(user, 0700)
	if result, err := ListBambuAccounts(context.Background(), root); result != nil || err != Code("source_unavailable") {
		t.Fatal("unreadable listing accepted")
	}
}

func TestAccountsRejectSameDeviceBind(t *testing.T) {
	if _, err := os.Stat("/accounts-mount/user/fixture-account"); err != nil {
		t.Skip("requires isolated account directory bind fixtures")
	}
	for _, root := range []string{"/accounts-mount", "/account-child-mount"} {
		var before, after syscall.Stat_t
		target := root + "/user"
		if root == "/account-child-mount" {
			target += "/fixture-account"
		}
		if syscall.Stat(root, &before) != nil || syscall.Stat(target, &after) != nil || before.Dev != after.Dev {
			t.Fatal("not a same-device bind fixture")
		}
		if result, err := ListBambuAccounts(context.Background(), root); result != nil || err != Code("source_unsafe") {
			t.Fatalf("account mount boundary lost: %v", err)
		}
	}
}
