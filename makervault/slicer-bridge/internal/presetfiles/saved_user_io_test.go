//go:build (linux || windows) && (amd64 || arm64)

package presetfiles

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"makersvault/slicer-bridge/internal/printerpreset"
)

const localSavedUser = `{"name":"Saved machine","from":"User","version":"02.08.02.61","inherits":"Printer","nozzle_diameter":["0.6"],"machine_end_gcode":"PRIVATE_SCRIPT","printhost_password":"PRIVATE_PASSWORD","user_id":"PRIVATE_ACCOUNT","bed_custom_texture":"PRIVATE_IMAGE_PATH"}`

// Uses pre-existing public APIs and fixtures so this exact test also serves as
// a failing-old-source regression control (the old reader rejects the shape).
func TestSavedUserDirectoryProjection(t *testing.T) {
	root := discoveryFixture(t)
	writeDiscoveryFixture(t, root, "user/private-account/machine/local-file.json", localSavedUser)
	discovery, err := DiscoverBambu(context.Background(), root, "private-account")
	if err != nil {
		t.Fatalf("saved-user discovery rejected: %v", err)
	}
	if len(discovery.Selections) != 2 || discovery.Selections[1].Name != "Saved machine" || discovery.HiddenMachines != 1 {
		t.Fatal(discovery)
	}
	candidates, err := SelectBambu(context.Background(), root, "private-account", []printerpreset.Selection{{Kind: printerpreset.User, Name: "Saved machine"}})
	if err != nil || len(candidates) != 1 {
		t.Fatal(err)
	}
	got := candidates[0]
	if !got.Complete() || *got.Nozzle != 0.6 || got.Provenance.Bed != "inherited" || got.Provenance.Nozzle != "source" {
		t.Fatal(got)
	}
	if got.Source.ApplicationVersion != "" || got.Source.BundleVersion != "1.2.3.4" {
		t.Fatal("file version promoted")
	}
	data, _ := json.Marshal(candidates)
	for _, private := range []string{root, "private-account", "local-file.json", "02.08.02.61", "PRIVATE_"} {
		if strings.Contains(string(data), private) {
			t.Fatal("private source field exported")
		}
	}
	// Generic explicitly supplied files do not establish machine-directory context.
	input := Input{Root: filepath.Join(root, "user", "private-account", "machine"), Files: []string{"local-file.json"}, Source: printerpreset.Source{Namespace: "local", Kind: printerpreset.User}}
	if catalog, err := LoadBambu(context.Background(), []Input{input}); catalog != nil || err != printerpreset.Code("invalid_machine_identity") {
		t.Fatal("generic loader gained authority", err)
	}
	// Reselection uses the current document name, not a cached discovery or filename.
	writeDiscoveryFixture(t, root, "user/private-account/machine/local-file.json", strings.Replace(localSavedUser, "Saved machine", "Renamed machine", 1))
	if candidates, err := SelectBambu(context.Background(), root, "private-account", []printerpreset.Selection{{Kind: printerpreset.User, Name: "Saved machine"}}); candidates != nil || err != printerpreset.Code("preset_not_found") {
		t.Fatal("stale selection reused", err)
	}
}

func TestSavedUserHiddenAndMissingParentAreNotGuessed(t *testing.T) {
	root := discoveryFixture(t)
	writeDiscoveryFixture(t, root, "user/private-account/machine/local-file.json", strings.Replace(localSavedUser, `"name":`, `"instantiation":false,"name":`, 1))
	if discovery, err := DiscoverBambu(context.Background(), root, "private-account"); err != nil || len(discovery.Selections) != 1 || discovery.HiddenMachines != 2 {
		t.Fatal(discovery, err)
	}
	// Do not open recursively nested custom base profiles or silently use defaults.
	nested := filepath.Join(root, "user/private-account/machine/base")
	if err := os.Mkdir(nested, 0700); err != nil {
		t.Fatal(err)
	}
	writeDiscoveryFixture(t, nested, "nested.json", `{"name":"Nested root","from":"User","version":"2.8.2.61"}`)
	writeDiscoveryFixture(t, root, "user/private-account/machine/local-file.json", strings.Replace(localSavedUser, `"inherits":"Printer"`, `"inherits":"Nested root"`, 1))
	if discovery, err := DiscoverBambu(context.Background(), root, "private-account"); discovery != nil || err != printerpreset.Code("missing_parent") {
		t.Fatal("nested source/default fallback", err)
	}
}

func TestSavedUserSidecarsAndOtherAccountsStayUnread(t *testing.T) {
	root := discoveryFixture(t)
	writeDiscoveryFixture(t, root, "user/private-account/machine/local-file.json", localSavedUser)
	writeDiscoveryFixture(t, root, "user/private-account/machine/local-file.info", "PRIVATE_ACCOUNT_INFO_NOT_JSON")
	other := filepath.Join(root, "user/other-account/machine")
	if err := os.MkdirAll(other, 0700); err != nil {
		t.Fatal(err)
	}
	writeDiscoveryFixture(t, other, "invalid.json", "MALFORMED_DO_NOT_READ")
	if discovery, err := DiscoverBambu(context.Background(), root, "private-account"); err != nil || len(discovery.Selections) != 2 {
		t.Fatal(discovery, err)
	}
	// Invalid chosen files abort; they are not treated as an absent optional account.
	writeDiscoveryFixture(t, root, "user/private-account/machine/local-file.json", strings.Replace(localSavedUser, "02.08.02.61", "PRIVATE_BAD_VERSION", 1))
	if discovery, err := DiscoverBambu(context.Background(), root, "private-account"); discovery != nil || err != printerpreset.Code("unsupported_user_version") {
		t.Fatal(discovery, err)
	}
	if discovery, err := DiscoverBambu(context.Background(), root, ""); err != nil || discovery.UserIncluded {
		t.Fatal("system-only reads user files", err)
	}
}
