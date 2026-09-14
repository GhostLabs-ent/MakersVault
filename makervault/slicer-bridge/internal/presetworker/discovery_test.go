package presetworker

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"makersvault/slicer-bridge/internal/presetfiles"
	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestWorkerDiscoveryAndSelectionRoundTrip(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		t.Skip("Windows/Linux content scan only")
	}
	root := t.TempDir()
	machine := filepath.Join(root, "system", "BBL", "machine")
	if err := os.MkdirAll(machine, 0700); err != nil {
		t.Fatal(err)
	}
	manifest := `{"name":"Bambulab","version":"1.2.3.4","machine_list":[{"name":"Printer","sub_path":"machine/private-file.json"}]}`
	if err := os.WriteFile(filepath.Join(root, "system", "BBL.json"), []byte(manifest), 0600); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(machine, "private-file.json")
	if err := os.WriteFile(file, []byte(`{"type":"machine","name":"Printer","instantiation":true,"credentials":"SYNTHETIC_SECRET"}`), 0600); err != nil {
		t.Fatal(err)
	}
	result, err := Run(context.Background(), Request{Operation: "discover", Root: root})
	if err != nil || result.Discovery == nil || !result.Discovery.Validate(false) || len(result.Discovery.Selections) != 1 {
		t.Fatal(result, err)
	}
	result, err = Run(context.Background(), Request{Operation: "select", Root: root, Picks: result.Discovery.Selections})
	if err != nil || len(result.Candidates) != 1 || result.Candidates[0].Complete() || len(result.Candidates[0].Reasons) == 0 {
		t.Fatal(result, err)
	}
	data, _ := json.Marshal(result)
	for _, private := range []string{root, "private-file.json", "SYNTHETIC_SECRET"} {
		if strings.Contains(string(data), private) {
			t.Fatal("private source escaped worker")
		}
	}
	if err := os.WriteFile(file, []byte(`{"type":"machine","name":"Wrong","instantiation":true}`), 0600); err != nil {
		t.Fatal(err)
	}
	for _, operation := range []string{"discover", "select"} {
		request := Request{Operation: operation, Root: root}
		if operation == "select" {
			request.Picks = []Pick{{Kind: printerpreset.System, Name: "Printer"}}
		}
		result, err := Run(context.Background(), request)
		if err != Code("manifest_identity_mismatch") || result.Discovery != nil || len(result.Candidates) != 0 {
			t.Fatal("partial or unbound worker result", err)
		}
	}
}

func TestWorkerDiscoveryAuthorityAndFraming(t *testing.T) {
	for _, request := range []Request{
		{Operation: "discover", Root: "/local", Picks: []Pick{{Kind: printerpreset.System, Name: "x"}}},
		{Operation: "discover", Root: "/local", Inputs: []presetfiles.Input{{Root: "/other"}}},
		{Operation: "discover", Root: "/local", Account: "../escape"},
		{Operation: "select", Root: "/local"},
		{Operation: "select", Root: "/local", Picks: []Pick{{Kind: printerpreset.System, Name: "x"}, {Kind: printerpreset.System, Name: "x"}}},
		{Operation: "select", Root: "/local", Picks: make([]Pick, MaxSelected+1)},
	} {
		if _, _, err := marshalRequest(request); err == nil {
			t.Fatal("cross-operation or unbounded request")
		}
	}
	discovery := &presetfiles.BambuDiscovery{BundleVersion: "1.2.3.4", Selections: []printerpreset.Selection{}}
	for _, result := range []envelope{
		{Version: 1},
		{Version: 1, Code: "source_unavailable", Response: Response{Discovery: discovery}},
		{Version: 1, Response: Response{Discovery: discovery, Names: []string{"a.json"}}},
		{Version: 1, Response: Response{Discovery: discovery, Location: &presetfiles.LocationInspection{}}},
		{Version: 1, Response: Response{Discovery: discovery, Candidates: []printerpreset.Candidate{{}}}},
	} {
		data, _ := json.Marshal(result)
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: "discover"}); err != Code("worker_response_invalid") {
			t.Fatal("mixed discovery frame")
		}
	}
	data, _ := json.Marshal(envelope{Version: 1, Response: Response{Discovery: discovery}})
	for _, operation := range []string{"list", "manifest", "location", "project", "select"} {
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: operation}); err != Code("worker_response_invalid") {
			t.Fatal("discovery on other operation")
		}
	}
	if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: "discover", Account: "chosen"}); err != Code("worker_response_invalid") {
		t.Fatal("missing account accepted")
	}
	data, _ = json.Marshal(Request{Operation: "select", Root: "/private", Account: "private"})
	if string(data) != "{}" {
		t.Fatal("public JSON carries path authority")
	}
}
