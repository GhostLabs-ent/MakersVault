package presetworker

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"makersvault/slicer-bridge/internal/presetfiles"
)

func TestWorkerManifestRoundTrip(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		t.Skip("new workstation preset import limited to Windows/Linux")
	}
	root := t.TempDir()
	const fixture = `{"name":"Bambulab","version":"02.08.00.05","url":"https://private.invalid",
	"machine_list":[{"name":"Fixture","sub_path":"machine/unread.json"}],
	"credentials":{"private":"FAKE_PRIVATE"}}`
	if err := os.WriteFile(filepath.Join(root, "BBL.json"), []byte(fixture), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("MAKERSVAULT_PARENT_SECRET", "SYNTHETIC_SECRET")
	response, err := Run(context.Background(), Request{Operation: "manifest", Root: root})
	if err != nil || response.Manifest == nil || response.Manifest.BundleVersion != "02.08.00.05" ||
		len(response.Manifest.Machines) != 1 || response.Manifest.Machines[0].File != "unread.json" {
		t.Fatalf("%+v %v", response, err)
	}
	data, _ := json.Marshal(response)
	for _, value := range []string{root, "FAKE_PRIVATE", "private.invalid", "SYNTHETIC_SECRET", "application_version"} {
		if strings.Contains(string(data), value) {
			t.Fatal("private value or invented app version in manifest response")
		}
	}
	if err := os.WriteFile(filepath.Join(root, "BBL.json"), []byte(fixture+"INVALID"), 0600); err != nil {
		t.Fatal(err)
	}
	response, err = Run(context.Background(), Request{Operation: "manifest", Root: root})
	if err != Code("manifest_invalid") || response.Manifest != nil || len(response.Names) != 0 || len(response.Candidates) != 0 {
		t.Fatalf("partial manifest: %+v %v", response, err)
	}
}

func TestWorkerManifestFraming(t *testing.T) {
	manifest := &presetfiles.BambuManifest{BundleVersion: "1.2.3.4", Machines: []presetfiles.ManifestEntry{{Name: "Fixture", File: "a.json"}}}
	for _, operation := range []string{"list", "project"} {
		data, _ := json.Marshal(envelope{Version: 1, Response: Response{Manifest: manifest}})
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: operation}); err != Code("worker_response_invalid") {
			t.Fatal("manifest in unrelated operation accepted")
		}
	}
	for _, frame := range []envelope{
		{Version: 1},
		{Version: 1, Code: "manifest_invalid", Response: Response{Manifest: manifest}},
		{Version: 1, Response: Response{Manifest: manifest, Names: []string{"a.json"}}},
		{Version: 1, Response: Response{Manifest: &presetfiles.BambuManifest{BundleVersion: "2.8.0.6"}}},
		{Version: 1, Response: Response{Manifest: &presetfiles.BambuManifest{BundleVersion: "2.8.0.6", Machines: []presetfiles.ManifestEntry{{Name: "Fixture", File: "../a.json"}}}}},
	} {
		data, _ := json.Marshal(frame)
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: "manifest"}); err != Code("worker_response_invalid") {
			t.Fatal("invalid or partial manifest response accepted")
		}
	}
	for _, request := range []Request{
		{Operation: "manifest", Root: "/private", Picks: []Pick{{Name: "Fixture"}}},
		{Operation: "manifest", Root: "/private", Inputs: []presetfiles.Input{{Root: "/elsewhere"}}},
		{Operation: "manifest"},
	} {
		if _, _, err := marshalRequest(request); err == nil {
			t.Fatal("manifest accepted authority from an unrelated operation")
		}
	}
}

func TestWorkerManifestResponseBudget(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		t.Skip("new workstation preset import limited to Windows/Linux")
	}
	// Under the vendor file/entry limits, over the private response ceiling. The
	// child must return only an error, not silently shorten the local index.
	var entries []string
	for i := 0; i < 6000; i++ {
		entries = append(entries, fmt.Sprintf(`{"name":"%s%d","sub_path":"machine/%s%d.json"}`,
			strings.Repeat("n", 190), i, strings.Repeat("f", 190), i))
	}
	data := `{"name":"Bambulab","version":"1.2.3.4","machine_list":[` + strings.Join(entries, ",") + `]}`
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "BBL.json"), []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
	response, err := Run(context.Background(), Request{Operation: "manifest", Root: root})
	if err != Code("worker_response_limit") || response.Manifest != nil || len(response.Names) != 0 || len(response.Candidates) != 0 {
		t.Fatalf("partial oversized index: %+v %v", response, err)
	}
}
