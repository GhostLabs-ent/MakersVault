package presetfiles

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestPortableJSONNames(t *testing.T) {
	for _, name := range []string{"P1S 0.4 nozzle.json", "café.JSON", "fdm_machine_common.json", "多色.json", "a.b.json"} {
		if !fileName(name) {
			t.Errorf("ordinary basename rejected: %q", name)
		}
	}
	for _, name := range []string{"", ".json", "../a.json", "/a.json", `sub\a.json`, `C:\a.json`,
		`\\server\a.json`, "https://server/a.json", "a.json:secret", "a.json ", " a.json", "a.json.",
		"a\x00.json", "a\n.json", "a\xff.json", "a?.json", "a*.json", "CON.json", "con.other.json",
		"NUL.json", "LPT1.json", "COM0.json", "COM¹.json", "LPT².json", "CONIN$.json",
		strings.Repeat("a", 251) + ".json", "a.ini", "folder/a.json"} {
		if fileName(name) {
			t.Errorf("unsafe basename accepted: %q", name)
		}
	}
}

func TestFilesystemAuthorityNotJSON(t *testing.T) {
	input := Input{Root: "/private/root", Files: []string{"private.json"},
		Source: printerpreset.Source{Namespace: "private-account", Kind: printerpreset.System}}
	data, err := json.Marshal(input)
	if err != nil || string(data) != "{}" {
		t.Fatalf("local authority serialized: %s %v", data, err)
	}
	var decoded Input
	if err := json.Unmarshal([]byte(`{"Root":"/arbitrary","Files":["a.json"]}`), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.Root != "" || decoded.Files != nil {
		t.Fatal("JSON conferred filesystem authority")
	}
}

func TestReaderCancellationBeforeFilesystem(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if names, err := ListJSON(ctx, "/no-read"); names != nil || err != Code("source_cancelled") {
		t.Fatalf("%v %v", names, err)
	}
	if catalog, err := LoadBambu(ctx, nil); catalog != nil || err != Code("source_cancelled") {
		t.Fatalf("%v %v", catalog, err)
	}
	ctx, cancel = context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	if _, err := ListJSON(ctx, "/no-read"); err != Code("source_time_budget_exceeded") {
		t.Fatal(err)
	}
	if _, err := LoadBambu(ctx, nil); err != Code("source_time_budget_exceeded") {
		t.Fatal(err)
	}
}

func TestSelectionValidation(t *testing.T) {
	for _, inputs := range [][]Input{nil, {{}, {}, {}}, {{Root: "/", Files: []string{"a.json"}}},
		{{Root: "relative", Files: []string{"a.json"}}}, {{Root: "/no-read"}},
		{{Root: "/no-read", Files: []string{"a.json"}, Source: printerpreset.Source{Kind: "unknown"}}}} {
		if catalog, err := LoadBambu(context.Background(), inputs); catalog != nil || err != Code("source_selection_invalid") {
			t.Fatalf("%v %v", catalog, err)
		}
	}
}

func FuzzPortableJSONName(f *testing.F) {
	for _, seed := range []string{"profile.json", "../escape.json", `\\host\share\x.json`, "COM1.json"} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, name string) {
		if fileName(name) && (len(name) > 255 || strings.ContainsAny(name, `/\:`) || !safeText(name)) {
			t.Fatal("unsafe filename passed")
		}
	})
}
