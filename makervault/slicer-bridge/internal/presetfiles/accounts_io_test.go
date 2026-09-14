//go:build (linux || windows) && (amd64 || arm64)

package presetfiles

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestAccountsAreNamesOnlyAndNeverSelected(t *testing.T) {
	root := locationFixture(t)
	for _, name := range []string{"z-account", "default", "A-account"} {
		if err := os.Mkdir(filepath.Join(root, "user", name), 0700); err != nil {
			t.Fatal(err)
		}
	}
	// These are invalid profiles/settings, but enumeration may not read them.
	if err := os.WriteFile(filepath.Join(root, "user", "sidecar.json"), []byte("PRIVATE_NOT_JSON"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "system", "BBL.json"), []byte("PRIVATE_NOT_A_MANIFEST"), 0600); err != nil {
		t.Fatal(err)
	}
	choices, err := ListBambuAccounts(context.Background(), root)
	if err != nil || choices == nil || !choices.Validate() ||
		!reflect.DeepEqual(choices.Names, []string{"A-account", "chosen-account", "default", "z-account"}) {
		t.Fatalf("wrong local choices: %v", err)
	}
	// An enumerated directory with no machine folder is not a usable preset claim.
	if result, err := InspectBambuLocation(context.Background(), root, "default"); result != nil || err == nil {
		t.Fatal("account enumeration qualified invalid profile data")
	}
}

func TestAccountsEmptyMissingAndInvalidRoot(t *testing.T) {
	root := t.TempDir()
	if result, err := ListBambuAccounts(context.Background(), root); result != nil || err != Code("source_unavailable") {
		t.Fatal("missing user silently treated as empty success")
	}
	if err := os.Mkdir(filepath.Join(root, "user"), 0700); err != nil {
		t.Fatal(err)
	}
	result, err := ListBambuAccounts(context.Background(), root)
	if err != nil || result == nil || !result.Validate() || len(result.Names) != 0 {
		t.Fatal("empty user directory rejected")
	}
	for _, path := range []string{"", ".", "relative", root + string(filepath.Separator) + ".."} {
		if result, err := ListBambuAccounts(context.Background(), path); result != nil || err != Code("source_path_invalid") {
			t.Fatal("unsafe root accepted")
		}
	}
}

func TestAccountsEntryBudgetIncludesSidecars(t *testing.T) {
	root := t.TempDir()
	for i := 0; i < 65; i++ {
		if err := os.WriteFile(filepath.Join(root, fmt.Sprintf("sidecar-%03d", i)), nil, 0600); err != nil {
			t.Fatal(err)
		}
	}
	for _, allowance := range []int{0, 64, 65} {
		dir, err := openDirectory(context.Background(), root)
		if err != nil {
			t.Fatal(err)
		}
		result, err := listAccounts(context.Background(), dir, allowance)
		dir.close()
		if allowance < 65 {
			if result != nil || err != Code("source_entry_limit_exceeded") {
				t.Fatal("ignored sidecars bypassed budget")
			}
		} else if result == nil || len(result) != 0 || err != nil {
			t.Fatal("exact entry budget failed")
		}
	}
}
