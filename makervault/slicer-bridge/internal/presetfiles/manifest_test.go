package presetfiles

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"makersvault/slicer-bridge/internal/printerpreset"
)

// Original synthetic data, not a retained vendor file or a device qualification.
const manifestFixture = `{"name":"Bambulab","version":"02.08.00.05",
"url":"https://private.invalid/do-not-fetch","credentials":{"value":"FAKE_PRIVATE"},
"machine_model_list":[{"name":"Model description","sub_path":"machine/model.json"}],
"filament_list":[{"name":"Filament","sub_path":"filament/private.json"}],
"process_list":[{"name":"Process","sub_path":"process/private.json"}],
"machine_list":[{"name":"Fixture P1S 0.4","sub_path":"machine/child.json"},
{"name":"Fixture base","sub_path":"machine/base.json"},
{"name":"Fixture script template","sub_path":"machine/script.json"}]}`

func TestManifestProjectionAndExactSelection(t *testing.T) {
	m, err := ParseBambuManifest(context.Background(), []byte(manifestFixture))
	if err != nil || m == nil || !m.Validate() || m.BundleVersion != "02.08.00.05" || len(m.Machines) != 3 {
		t.Fatalf("%+v %v", m, err)
	}
	files, err := m.SelectFiles([]string{"Fixture base", "Fixture P1S 0.4"})
	if err != nil || !reflect.DeepEqual(files, []string{"base.json", "child.json"}) {
		t.Fatalf("%v %v", files, err)
	}
	// The index includes templates but deliberately has no selectable flag. The
	// existing parser must check document type/instantiation before any UI offer.
	data, _ := json.Marshal(m)
	for _, excluded := range []string{"FAKE_PRIVATE", "private.invalid", "credentials", "Model description", "Filament", "Process", "application_version", "sub_path"} {
		if strings.Contains(string(data), excluded) {
			t.Fatalf("discarded field leaked: %s", excluded)
		}
	}
	for _, names := range [][]string{nil, {"fixture base"}, {"Fixture base", "Fixture base"},
		{"Fixture base", "Missing"}, {"Model description"}, {"child.json"}, {"../child.json"}, make([]string, MaxEntries+1)} {
		if files, err := m.SelectFiles(names); files != nil || err != Code("manifest_selection_invalid") {
			t.Fatalf("partial or implicit selection: %v %v", files, err)
		}
	}
}

func TestManifestRejectsAmbiguityAndUnsafeReferences(t *testing.T) {
	for _, path := range []string{"../child.json", "/machine/a.json", `machine\a.json`, "machine/../a.json", "machine/nested/a.json",
		"machine/C:secret.json", "machine/CON.json", "machine/a.json ", "machine/.json", "https://host/a.json", "filament/a.json", "machine/a.gcode"} {
		t.Run(path, func(t *testing.T) {
			encoded, _ := json.Marshal(path)
			data := strings.Replace(manifestFixture, `"machine/child.json"`, string(encoded), 1)
			if m, err := ParseBambuManifest(context.Background(), []byte(data)); m != nil || err != Code("manifest_invalid") {
				t.Fatalf("unsafe reference accepted: %v %v", m, err)
			}
		})
	}
	for _, replacement := range []struct{ old, next string }{
		{`"Fixture base"`, `"Fixture P1S 0.4"`},
		{`"machine/base.json"`, `"machine/CHILD.JSON"`},
		{`"name":"Bambulab"`, `"name":"Bambulab","Name":"Bambulab"`},
		{`"value":"FAKE_PRIVATE"`, `"value":"FAKE_PRIVATE","value":"second"`},
		{`"value":"FAKE_PRIVATE"`, `"valúe":"FAKE_PRIVATE"`},
		{`"sub_path":"machine/child.json"`, `"sub_path":"machine/child.json","sub_path":"machine/x.json"`},
		{`"version":"02.08.00.05"`, `"version":"2.8.0.6 secret"`},
		{`"version":"02.08.00.05"`, `"version":2`},
		{`"version":"02.08.00.05"`, `"version":""`},
		{`"version":"02.08.00.05"`, `"version":"2.8.0"`},
		{`"Fixture base"`, `""`},
		{`"Fixture base"`, `"bad\nname"`},
		{`"Fixture base"`, `"` + strings.Repeat("x", 201) + `"`},
		{`"Fixture base"`, `" private "`},
	} {
		data := strings.Replace(manifestFixture, replacement.old, replacement.next, 1)
		if m, err := ParseBambuManifest(context.Background(), []byte(data)); m != nil || err != Code("manifest_invalid") {
			t.Fatalf("invalid manifest accepted: %s %v", replacement.next, err)
		}
	}
}

func TestManifestStrictFramingAndSchema(t *testing.T) {
	for _, data := range []string{"null", "[]", "{}", `{"name":"Bambulab","version":"02.08.00.05"}`,
		`{"name":"Bambulab","version":"02.08.00.05","machine_list":null}`,
		`{"name":"Bambulab","version":"02.08.00.05","machine_list":[null]}`,
		`{"name":"Bambulab","version":"02.08.00.05","machine_list":[{}]}`,
		manifestFixture + "{}", strings.Replace(manifestFixture, "Bambulab", "Orca", 1),
		strings.Replace(manifestFixture, "Bambulab", "Bambu\xfflab", 1),
		strings.Replace(manifestFixture, `"url":`, `"schema_version":1,"url":`, 1),
		strings.Replace(manifestFixture, `"url":`, `"format_version":1,"url":`, 1)} {
		if m, err := ParseBambuManifest(context.Background(), []byte(data)); m != nil || err == nil {
			t.Fatalf("invalid framing/schema accepted: %v", m)
		}
	}
	if m, err := ParseBambuManifest(context.Background(), []byte(`{"name":"Bambulab","version":"1.2.3.4","machine_list":[]}`)); err != nil || m == nil || len(m.Machines) != 0 {
		t.Fatalf("explicit empty list rejected: %v %v", m, err)
	}
}

func TestManifestBudgetsAndCancellation(t *testing.T) {
	for _, tc := range []struct {
		data string
		code Code
	}{
		{strings.Repeat(" ", printerpreset.MaxFileBytes+1), "manifest_bytes_exceeded"},
		{strings.Replace(manifestFixture, `"FAKE_PRIVATE"`, strings.Repeat("[", 17)+"0"+strings.Repeat("]", 17), 1), "manifest_structure_limit"},
		{strings.Replace(manifestFixture, `"FAKE_PRIVATE"`, "["+strings.Repeat("0,", 250000)+"0]", 1), "manifest_structure_limit"},
	} {
		if m, err := ParseBambuManifest(context.Background(), []byte(tc.data)); m != nil || err != tc.code {
			t.Fatalf("budget: %v %v, want %v", m, err, tc.code)
		}
	}
	var entries []string
	for i := 0; i <= MaxEntries; i++ {
		entries = append(entries, fmt.Sprintf(`{"name":"Preset %d","sub_path":"machine/p%d.json"}`, i, i))
	}
	data := `{"name":"Bambulab","version":"1.2.3.4","machine_list":[` + strings.Join(entries, ",") + `]}`
	if m, err := ParseBambuManifest(context.Background(), []byte(data)); m != nil || err != Code("manifest_entry_limit") {
		t.Fatalf("entry budget: %v %v", m, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if m, err := ParseBambuManifest(ctx, []byte(manifestFixture)); m != nil || err != Code("source_cancelled") {
		t.Fatal(err)
	}
	if m, err := ReadBambuManifest(ctx, "/never-read"); m != nil || err != Code("source_cancelled") {
		t.Fatal(err)
	}
}

func FuzzBambuManifest(f *testing.F) {
	for _, seed := range []string{manifestFixture, `null`, `{"name":"Bambulab","version":"1.2.3.4","machine_list":[]}`} {
		f.Add([]byte(seed))
	}
	f.Fuzz(func(t *testing.T, data []byte) {
		m, err := ParseBambuManifest(context.Background(), data)
		if err != nil {
			if m != nil {
				t.Fatal("partial index escaped")
			}
			return
		}
		if m == nil || !m.Validate() {
			t.Fatal("invalid index accepted")
		}
	})
}
