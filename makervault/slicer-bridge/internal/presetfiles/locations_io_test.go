//go:build (linux || windows) && (amd64 || arm64)

package presetfiles

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func locationFixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	for _, parts := range [][]string{{"system", "BBL", "machine"}, {"user", "chosen-account", "machine"}} {
		if err := os.MkdirAll(filepath.Join(append([]string{root}, parts...)...), 0700); err != nil {
			t.Fatal(err)
		}
	}
	for _, file := range []struct{ name, data string }{
		{filepath.Join("system", "BBL.json"), manifestFixture},
		{"BambuStudio.conf", "FAKE_GENERAL_CONFIGURATION"},
		{filepath.Join("user", "chosen-account", "machine", "b.json"), "FAKE_PROFILE_BODY_NOT_PARSED"},
		{filepath.Join("user", "chosen-account", "machine", "a.json"), "FAKE_PROFILE_BODY_NOT_PARSED"},
	} {
		if err := os.WriteFile(filepath.Join(root, file.name), []byte(file.data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func TestLocationInspectionAnchoredAndExplicit(t *testing.T) {
	root := locationFixture(t)
	for _, account := range []string{"", "chosen-account"} {
		result, err := InspectBambuLocation(context.Background(), root, account)
		if err != nil || result == nil || !result.Validate(account != "") {
			t.Fatalf("%v %v", result, err)
		}
		if account != "" && !reflect.DeepEqual(result.UserFiles, []string{"a.json", "b.json"}) {
			t.Fatal(result.UserFiles)
		}
		data, _ := json.Marshal(result)
		for _, private := range []string{root, "chosen-account", "FAKE_GENERAL_CONFIGURATION", "FAKE_PROFILE_BODY_NOT_PARSED"} {
			if strings.Contains(string(data), private) {
				t.Fatal("private location data in observation")
			}
		}
	}
	// Empty selection must not guess default or touch user folders.
	if err := os.Rename(filepath.Join(root, "user"), filepath.Join(root, "unselected-user")); err != nil {
		t.Fatal(err)
	}
	if result, err := InspectBambuLocation(context.Background(), root, ""); err != nil || result.UserIncluded {
		t.Fatal(err)
	}
	if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); result != nil || err == nil {
		t.Fatal("missing account silently ignored")
	}
	data, err := os.ReadFile(filepath.Join(root, "BambuStudio.conf"))
	if err != nil || string(data) != "FAKE_GENERAL_CONFIGURATION" {
		t.Fatal("source changed")
	}
}

func TestLocationInvalidSelectionAndIncompleteLayout(t *testing.T) {
	root := t.TempDir()
	for _, account := range []string{"../escape", "a/b", `a\b`, "NUL", "a:", ".", "..", "a.", " a", "bad\nname"} {
		if result, err := InspectBambuLocation(context.Background(), root, account); result != nil || err != Code("source_path_invalid") {
			t.Fatal(err)
		}
	}
	for _, relative := range []string{"system", filepath.Join("system", "BBL"), filepath.Join("system", "BBL", "machine"), filepath.Join("user", "chosen-account", "machine")} {
		root := locationFixture(t)
		if err := os.Rename(filepath.Join(root, relative), filepath.Join(root, "removed-for-fixture")); err != nil {
			t.Fatal(err)
		}
		if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); result != nil || err == nil {
			t.Fatal("partial location escaped")
		}
	}
}

func TestLocationSharedEntryBudget(t *testing.T) {
	root := locationFixture(t)
	entries := make([]ManifestEntry, MaxEntries-1)
	var raw []string
	for i := range entries {
		raw = append(raw, fmt.Sprintf(`{"name":"Fixture %d","sub_path":"machine/p%d.json"}`, i, i))
	}
	data := `{"name":"Bambulab","version":"1.2.3.4","machine_list":[` + strings.Join(raw, ",") + `]}`
	if err := os.WriteFile(filepath.Join(root, "system", "BBL.json"), []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
	if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); result != nil || err != Code("source_entry_limit_exceeded") {
		t.Fatalf("budget reset: %v %v", result, err)
	}
	// With exactly one user entry the combined limit is accepted; referenced
	// system documents still do not exist and are not opened by this operation.
	if err := os.Rename(filepath.Join(root, "user", "chosen-account", "machine", "b.json"), filepath.Join(root, "moved-fixture")); err != nil {
		t.Fatal(err)
	}
	if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); err != nil || !result.Validate(true) {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "user", "chosen-account", "machine", "ignored.txt"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	if result, err := InspectBambuLocation(context.Background(), root, "chosen-account"); result != nil || err != Code("source_entry_limit_exceeded") {
		t.Fatal("ignored entries escaped the shared directory budget")
	}
}
