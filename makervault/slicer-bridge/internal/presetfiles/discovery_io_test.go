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

	"makersvault/slicer-bridge/internal/printerpreset"
)

const discoveryBase = `{"type":"machine","name":"Base","instantiation":false,"printer_technology":"FFF","printer_structure":"corexy","printable_area":["0x0","200x0","200x200","0x200"],"printable_height":"200","bed_exclude_area":[],"nozzle_diameter":["0.4"]}`
const discoveryChild = `{"type":"machine","name":"Printer","instantiation":true,"inherits":"Base","include":["Printer template machine_start_gcode"],"machine_start_gcode":"FAKE_PRIVATE_SCRIPT","secret":"FAKE_PRIVATE_CREDENTIAL"}`
const discoveryUser = `{"type":"machine","name":"My printer","instantiation":"true","inherits":"Printer","from":"User"}`
const discoveryManifest = `{"name":"Bambulab","version":"1.2.3.4","machine_list":[{"name":"Printer","sub_path":"machine/not-the-name.json"},{"name":"Base","sub_path":"machine/base.json"},{"name":"Printer template machine_start_gcode","sub_path":"machine/include-trap.json"}]}`

func writeDiscoveryFixture(t *testing.T, root, relative, data string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, relative), []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
}

func discoveryFixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	for _, parts := range [][]string{{"system", "BBL", "machine"}, {"user", "private-account", "machine"}} {
		if err := os.MkdirAll(filepath.Join(append([]string{root}, parts...)...), 0700); err != nil {
			t.Fatal(err)
		}
	}
	for relative, data := range map[string]string{
		"system/BBL.json":                              discoveryManifest,
		"system/BBL/machine/base.json":                 discoveryBase,
		"system/BBL/machine/not-the-name.json":         discoveryChild,
		"system/BBL/machine/unlisted.json":             "MALFORMED_NOT_READ",
		"system/BBL/machine/include-trap.json":         "MALFORMED_INCLUDE_NOT_READ",
		"BambuStudio.conf":                             "FAKE_PRIVATE_SETTINGS",
		"user/private-account/machine/local-file.json": discoveryUser,
	} {
		writeDiscoveryFixture(t, root, relative, data)
	}
	return root
}

func TestDiscoveryBindsNamesResolvesParentsAndFiltersScripts(t *testing.T) {
	root := discoveryFixture(t)
	for _, account := range []string{"", "private-account"} {
		got, err := DiscoverBambu(context.Background(), root, account)
		if err != nil || got == nil || !got.Validate(account != "") {
			t.Fatalf("%v %v", got, err)
		}
		want := []printerpreset.Selection{{Kind: printerpreset.System, Name: "Printer"}}
		if account != "" {
			want = append(want, printerpreset.Selection{Kind: printerpreset.User, Name: "My printer"})
		}
		if !reflect.DeepEqual(got.Selections, want) || got.HiddenMachines != 1 || got.ExcludedScripts != 1 {
			t.Fatal(got)
		}
		candidates, err := SelectBambu(context.Background(), root, account, want)
		if err != nil || len(candidates) != len(want) {
			t.Fatal(err)
		}
		for _, candidate := range candidates {
			if !candidate.Complete() || candidate.Source.ApplicationVersion != "" || candidate.Source.BundleVersion != "1.2.3.4" {
				t.Fatal(candidate)
			}
		}
		data, _ := json.Marshal(struct {
			Discovery  *BambuDiscovery
			Candidates []printerpreset.Candidate
		}{got, candidates})
		for _, private := range []string{root, "private-account", "not-the-name.json", "local-file.json", "FAKE_PRIVATE", "include-trap"} {
			if strings.Contains(string(data), private) {
				t.Fatal("private source data escaped")
			}
		}
	}
	// Discovery has no cached authority: selection rereads and refuses renamed data.
	writeDiscoveryFixture(t, root, "system/BBL/machine/not-the-name.json", strings.Replace(discoveryChild, `"name":"Printer"`, `"name":"Renamed"`, 1))
	if result, err := SelectBambu(context.Background(), root, "", []printerpreset.Selection{{Kind: printerpreset.System, Name: "Printer"}}); result != nil || err != printerpreset.Code("manifest_identity_mismatch") {
		t.Fatal(err)
	}
}

func TestDiscoveryFailsAtomicallyOnIdentityAndGraphErrors(t *testing.T) {
	for _, tc := range []struct {
		name, file, data string
		want             printerpreset.Code
	}{
		{"identity", "system/BBL/machine/not-the-name.json", strings.Replace(discoveryChild, `"name":"Printer"`, `"name":"printer"`, 1), "manifest_identity_mismatch"},
		{"missing", "system/BBL/machine/base.json", strings.Replace(discoveryBase, `"instantiation":false`, `"instantiation":false,"inherits":"Absent"`, 1), "missing_parent"},
		{"cycle", "system/BBL/machine/base.json", strings.Replace(discoveryBase, `"instantiation":false`, `"instantiation":false,"inherits":"Printer"`, 1), "inheritance_cycle"},
		{"unsupported-include", "system/BBL/machine/not-the-name.json", strings.Replace(discoveryChild, "Printer template machine_start_gcode", "other-geometry", 1), "unsupported_include"},
		{"script-parent", "system/BBL/machine/not-the-name.json", strings.Replace(discoveryChild, `"inherits":"Base"`, `"inherits":"Printer template machine_start_gcode"`, 1), "missing_parent"},
		{"wrong-type", "system/BBL/machine/not-the-name.json", strings.Replace(discoveryChild, `"machine"`, `"filament"`, 1), "invalid_machine_identity"},
		{"saved-user-without-machine-headers", "user/private-account/machine/local-file.json", `{"name":"Local saved preset","from":"User","version":"2.8.0.6","inherits":"Printer"}`, "invalid_machine_identity"},
		{"future-schema", "system/BBL/machine/not-the-name.json", strings.Replace(discoveryChild, `"type":`, `"schema_version":99,"type":`, 1), "unsupported_source_schema"},
		{"ambiguous-parent", "user/private-account/machine/extra.json", `{"type":"machine","name":"Printer","instantiation":false}`, "ambiguous_parent"},
		{"duplicate-user", "user/private-account/machine/extra.json", discoveryUser, "ambiguous_identity"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := discoveryFixture(t)
			writeDiscoveryFixture(t, root, tc.file, tc.data)
			got, err := DiscoverBambu(context.Background(), root, "private-account")
			if got != nil || err != tc.want {
				t.Fatalf("%v %v", got, err)
			}
		})
	}
}

func TestDiscoverySelectionLimitsAndIncompleteGeometry(t *testing.T) {
	root := discoveryFixture(t)
	for _, picks := range [][]printerpreset.Selection{nil, {{Kind: printerpreset.System, Name: "Printer"}, {Kind: printerpreset.System, Name: "Printer"}}, make([]printerpreset.Selection, MaxSelected+1)} {
		if got, err := SelectBambu(context.Background(), root, "", picks); got != nil || err != Code("source_selection_invalid") {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"Base", "printer", "not-the-name.json"} {
		if got, err := SelectBambu(context.Background(), root, "", []printerpreset.Selection{{Kind: printerpreset.System, Name: name}}); got != nil || err == nil {
			t.Fatal("guessed selection")
		}
	}
	writeDiscoveryFixture(t, root, "system/BBL/machine/base.json", `{"type":"machine","name":"Base"}`)
	got, err := SelectBambu(context.Background(), root, "", []printerpreset.Selection{{Kind: printerpreset.System, Name: "Printer"}})
	if err != nil || len(got) != 1 || got[0].Complete() || len(got[0].Reasons) == 0 {
		t.Fatal("geometry invented", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if got, err := DiscoverBambu(ctx, root, ""); got != nil || err != Code("source_cancelled") {
		t.Fatal(err)
	}
}

func TestDiscoveryHiddenOrMissingInstantiationNotOffered(t *testing.T) {
	root := discoveryFixture(t)
	for _, value := range []string{`"instantiation":false,`, `"instantiation":"false",`, ""} {
		writeDiscoveryFixture(t, root, "system/BBL/machine/not-the-name.json", strings.Replace(discoveryChild, `"instantiation":true,`, value, 1))
		got, err := DiscoverBambu(context.Background(), root, "")
		if err != nil || len(got.Selections) != 0 || got.HiddenMachines != 2 {
			t.Fatal(got, err)
		}
	}
}

func TestDiscoveryFileCountIncludesIndexAndExcludedScripts(t *testing.T) {
	root := discoveryFixture(t)
	entries := []string{}
	for i := 0; i < MaxEntries; i++ {
		entries = append(entries, fmt.Sprintf(`{"name":"%d template machine_start_gcode","sub_path":"machine/s%d.json"}`, i, i))
	}
	writeDiscoveryFixture(t, root, "system/BBL.json", `{"name":"Bambulab","version":"1.2.3.4","machine_list":[`+strings.Join(entries, ",")+`]}`)
	if got, err := DiscoverBambu(context.Background(), root, ""); got != nil || err != Code("source_entry_limit_exceeded") {
		t.Fatal("index budget reset", err)
	}
}

func TestDiscoveryAggregateBudgetAlsoChargesManifest(t *testing.T) {
	root := discoveryFixture(t)
	catalog := printerpreset.NewBambu(context.Background())
	padding := strings.Repeat(" ", printerpreset.MaxFileBytes)
	for i := 0; i < printerpreset.MaxTotalBytes/printerpreset.MaxFileBytes; i++ {
		if _, err := catalog.ReadIndex(strings.NewReader(padding)); err != nil {
			t.Fatal(err)
		}
	}
	if session, err := openBambuLocation(context.Background(), root, "", catalog); session != nil || err != printerpreset.Code("total_bytes_exceeded") {
		t.Fatal("manifest reset aggregate budget", err)
	}
}
