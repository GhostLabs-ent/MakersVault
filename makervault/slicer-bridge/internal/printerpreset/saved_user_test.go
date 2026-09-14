package printerpreset

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
	"time"
)

const savedUserFixture = `{"name":"My machine","from":"User","version":"2.8.2.61","inherits":"Base","nozzle_diameter":["0.6"],"machine_start_gcode":"PRIVATE_SCRIPT","printhost_apikey":"PRIVATE_KEY","user_id":"PRIVATE_ACCOUNT","bed_custom_model":"PRIVATE_PATH"}`

var savedUserSource = Source{Namespace: "synthetic", Kind: User, BundleVersion: "01.02.03.04"}

func TestSavedUserMachineContextAndPrivacy(t *testing.T) {
	c := NewBambu(context.Background())
	parent := base("Base")
	parent["instantiation"] = false
	add(t, c, system, parent)
	if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(savedUserFixture)); err != nil {
		t.Fatal(err)
	}
	picks, err := c.Selections(system.Namespace)
	if err != nil || !reflect.DeepEqual(picks, []Selection{{Kind: User, Name: "My machine"}}) {
		t.Fatal(picks, err)
	}
	candidate, err := c.Resolve(system.Namespace, User, "My machine")
	if err != nil || !candidate.Complete() || *candidate.Nozzle != 0.6 || candidate.Provenance.Nozzle != "source" || candidate.Provenance.Bed != "inherited" {
		t.Fatal(candidate, err)
	}
	if candidate.Source.ApplicationVersion != "" || candidate.Source.BundleVersion != savedUserSource.BundleVersion {
		t.Fatal("file version promoted to observed version")
	}
	data, _ := json.Marshal(candidate)
	if strings.Contains(string(data), "PRIVATE_") || strings.Contains(string(data), "2.8.2.61") {
		t.Fatal("discarded metadata exported")
	}
	doc := c.documents[key{system.Namespace, User, "My machine"}]
	for _, field := range []string{"version", "type", "instantiation", "printhost_apikey", "machine_start_gcode"} {
		if _, ok := doc.fields[field]; ok {
			t.Fatalf("raw header invented/retained: %s", field)
		}
	}
}

func TestSavedUserCannotRelaxGenericOrSystemParser(t *testing.T) {
	for _, source := range []Source{system, savedUserSource} {
		c := NewBambu(context.Background())
		if err := c.Add(source, strings.NewReader(savedUserFixture)); err != Code("invalid_machine_identity") {
			t.Fatal("generic schema relaxed", err)
		}
	}
	c := NewBambu(context.Background())
	if err := c.AddLocalUserMachine(system, strings.NewReader(savedUserFixture)); err != Code("invalid_source") {
		t.Fatal(err)
	}
	if _, err := c.Selections(system.Namespace); err != Code("catalog_incomplete") {
		t.Fatal(err)
	}
	// A document flag or user source label cannot grant machine-folder context.
	raw := strings.Replace(savedUserFixture, `"name":`, `"localUserMachine":true,"name":`, 1)
	if err := NewBambu(context.Background()).Add(savedUserSource, strings.NewReader(raw)); err != Code("invalid_machine_identity") {
		t.Fatal(err)
	}
	c = NewBambu(context.Background())
	if err := c.Add(savedUserSource, strings.NewReader(`{"type":"machine","name":"x"}`)); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Resolve(system.Namespace, User, "x"); err != Code("not_selectable") {
		t.Fatal("generic absent instantiation changed", err)
	}
}

func TestSavedUserExplicitHeadersAndStandaloneIncomplete(t *testing.T) {
	for _, tc := range []struct {
		suffix     string
		selectable bool
	}{
		{"", true}, {`,"type":"machine"`, true}, {`,"instantiation":true`, true},
		{`,"instantiation":"true"`, true}, {`,"instantiation":false`, false}, {`,"instantiation":"false"`, false},
	} {
		c := NewBambu(context.Background())
		raw := `{"name":"Standalone","from":"User","version":"2.8.2","inherits":""` + tc.suffix + `}`
		if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(raw)); err != nil {
			t.Fatal(err)
		}
		candidate, err := c.Resolve(system.Namespace, User, "Standalone")
		if !tc.selectable {
			if err != Code("not_selectable") {
				t.Fatal(err)
			}
			continue
		}
		if err != nil || candidate.Complete() || len(candidate.Reasons) == 0 {
			t.Fatal("standalone geometry invented", err)
		}
	}
}

func TestSavedUserRejectsMalformedHeadersAndSchemas(t *testing.T) {
	for _, tc := range []struct {
		old, replacement string
		want             Code
	}{
		{`"from":"User"`, `"from":"Project"`, "source_kind_mismatch"},
		{`"from":"User",`, ``, "source_kind_mismatch"},
		{`"version":"2.8.2.61",`, ``, "unsupported_user_version"},
		{`"version":"2.8.2.61"`, `"version":null`, "unsupported_user_version"},
		{`"version":"2.8.2.61"`, `"version":2.8`, "unsupported_user_version"},
		{`"version":"2.8.2.61"`, `"version":"PRIVATE_VERSION"`, "unsupported_user_version"},
		{`"version":"2.8.2.61"`, `"version":"2.8.2-beta"`, "unsupported_user_version"},
		{`"version":"2.8.2.61"`, `"Version":"2.8.2.61"`, "invalid_json_key"},
		{`"name":"My machine"`, `"name":"x","type":"filament"`, "invalid_machine_identity"},
		{`"name":"My machine"`, `"name":"x","type":null`, "invalid_machine_identity"},
		{`"name":"My machine"`, `"name":"x","schema_version":99`, "unsupported_source_schema"},
		{`"name":"My machine"`, `"name":"x","instantiation":null`, "invalid_instantiation"},
		{`"name":"My machine"`, `"name":"x","instantiation":"yes"`, "invalid_instantiation"},
		{`"name":"My machine"`, `"name":"x","instantiation":[]`, "invalid_instantiation"},
		{`"name":"My machine"`, `"name":"Printer template machine_start_gcode"`, "invalid_machine_identity"},
	} {
		t.Run(string(tc.want)+tc.replacement, func(t *testing.T) {
			c := NewBambu(context.Background())
			err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(strings.Replace(savedUserFixture, tc.old, tc.replacement, 1)))
			if err != tc.want {
				t.Fatalf("want %s got %v", tc.want, err)
			}
			if _, err := c.Selections(system.Namespace); err != Code("catalog_incomplete") {
				t.Fatal("failure not latched", err)
			}
		})
	}
}

func TestSavedUserVersionGrammarAndNoVersionInheritance(t *testing.T) {
	for _, version := range []string{"2.8.2", "02.08.02.61", "0.0.0.0", "99999.99999.99999.99999"} {
		if !savedUserVersion(version) {
			t.Fatal(version)
		}
	}
	for _, version := range []string{"", "2.8", "2.8.2.61.1", "2..8.1", "-2.8.2", "2.8.2+build", "2.8.2\n", "2.8.2 ", "２.8.2", "100000.8.2"} {
		if savedUserVersion(version) {
			t.Fatal(version)
		}
	}
	c := NewBambu(context.Background())
	parent := base("Base")
	parent["version"] = "2.8.2.61"
	add(t, c, system, parent)
	raw := strings.Replace(savedUserFixture, `"version":"2.8.2.61",`, "", 1)
	if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(raw)); err != Code("unsupported_user_version") {
		t.Fatal("version inherited", err)
	}
}

func TestSavedUserExactGraphFailures(t *testing.T) {
	for _, tc := range []struct {
		parent string
		want   Code
	}{{"Missing", "missing_parent"}, {"My machine", "inheritance_cycle"}, {"base", "missing_parent"}, {"Printer template machine_start_gcode", "missing_parent"}} {
		c := NewBambu(context.Background())
		add(t, c, system, base("Base"))
		raw := strings.Replace(savedUserFixture, `"inherits":"Base"`, `"inherits":"`+tc.parent+`"`, 1)
		if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(raw)); err != nil {
			t.Fatal(err)
		}
		if picks, err := c.Selections(system.Namespace); picks != nil || err != tc.want {
			t.Fatal(picks, err)
		}
	}
	c := NewBambu(context.Background())
	add(t, c, system, base("Base"))
	for _, raw := range []string{`{"name":"Base","from":"User","version":"2.8.2.61"}`, savedUserFixture} {
		if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(raw)); err != nil {
			t.Fatal(err)
		}
	}
	if picks, err := c.Selections(system.Namespace); picks != nil || err != Code("ambiguous_parent") {
		t.Fatal(picks, err)
	}
}

func TestSavedUserUsesExistingBudgetsAndCancellation(t *testing.T) {
	for _, tc := range []struct {
		count   int
		bytes   int64
		expired bool
		want    Code
	}{
		{MaxFiles, 0, false, "file_count_exceeded"}, {0, MaxTotalBytes, false, "total_bytes_exceeded"}, {0, 0, true, "time_budget_exceeded"},
	} {
		c := NewBambu(context.Background())
		c.files = tc.count
		c.bytes = tc.bytes
		if tc.expired {
			c.started = time.Now().Add(-MaxDuration)
		}
		if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(savedUserFixture)); err != tc.want {
			t.Fatal(err)
		}
	}
	c := NewBambu(context.Background())
	if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(strings.Repeat(" ", MaxFileBytes+1))); err != Code("file_bytes_exceeded") {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	c = NewBambu(ctx)
	if err := c.AddLocalUserMachine(savedUserSource, cancelReader{cancel}); err != Code("cancelled") {
		t.Fatal(err)
	}
	c = NewBambu(context.Background())
	if err := c.AddLocalUserMachine(savedUserSource, brokenReader{}); err != Code("read_failed") {
		t.Fatal(err)
	}
}

func FuzzBambuSavedUserMachine(f *testing.F) {
	f.Add([]byte(savedUserFixture))
	f.Add([]byte(`{"name":"x","from":"User","version":"2.8.2","instantiation":false}`))
	f.Fuzz(func(t *testing.T, data []byte) {
		if len(data) > 16384 {
			return
		}
		c := NewBambu(context.Background())
		if err := c.AddLocalUserMachine(savedUserSource, strings.NewReader(string(data))); err != nil {
			if _, ok := err.(Code); !ok {
				t.Fatal("unredacted error")
			}
			return
		}
		picks, err := c.Selections(savedUserSource.Namespace)
		if err != nil {
			if picks != nil {
				t.Fatal("partial choices")
			}
			return
		}
		for _, pick := range picks {
			candidate, err := c.Resolve(savedUserSource.Namespace, pick.Kind, pick.Name)
			if err != nil {
				t.Fatal(err)
			}
			if candidate.Source.Kind != User || candidate.Source.ApplicationVersion != "" || candidate.Source.BundleVersion != savedUserSource.BundleVersion {
				t.Fatal("source authority changed")
			}
			if _, err := json.Marshal(candidate); err != nil {
				t.Fatal(err)
			}
		}
	})
}
