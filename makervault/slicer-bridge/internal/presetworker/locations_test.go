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
)

func TestWorkerLocationRoundTripAndAtomicFailure(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		t.Skip("new location scans are Windows/Linux only")
	}
	root := t.TempDir()
	for _, parts := range [][]string{{"system", "BBL", "machine"}, {"user", "private-account", "machine"}} {
		if err := os.MkdirAll(filepath.Join(append([]string{root}, parts...)...), 0700); err != nil {
			t.Fatal(err)
		}
	}
	const manifest = `{"name":"Bambulab","version":"1.2.3.4","machine_list":[{"name":"Fixture","sub_path":"machine/unread.json"}]}`
	if err := os.WriteFile(filepath.Join(root, "system", "BBL.json"), []byte(manifest), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "user", "private-account", "machine", "user.json"), []byte("PRIVATE_NOT_JSON_NOT_READ"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("MAKERSVAULT_PARENT_SECRET", "SYNTHETIC_SECRET")
	for _, account := range []string{"", "private-account"} {
		result, err := Run(context.Background(), Request{Operation: "location", Root: root, Account: account})
		if err != nil || result.Location == nil || !result.Location.Validate(account != "") {
			t.Fatalf("%+v %v", result, err)
		}
		if account != "" && strings.Join(result.Location.UserFiles, ",") != "user.json" {
			t.Fatal("wrong selected account listing")
		}
		data, _ := json.Marshal(result)
		for _, private := range []string{root, "private-account", "PRIVATE_NOT_JSON_NOT_READ", "SYNTHETIC_SECRET"} {
			if strings.Contains(string(data), private) {
				t.Fatal("location privacy boundary failed")
			}
		}
	}
	result, err := Run(context.Background(), Request{Operation: "location", Root: root, Account: "absent-account"})
	if err == nil || result.Location != nil || result.Manifest != nil || len(result.Names) != 0 || len(result.Candidates) != 0 {
		t.Fatal("partial result or implicit account fallback")
	}
	if strings.Contains(err.Error(), root) || strings.Contains(err.Error(), "absent-account") {
		t.Fatal("private path/account in error")
	}
}

func TestWorkerLocationRequestAndResponseFraming(t *testing.T) {
	for _, request := range []Request{
		{Operation: "location"},
		{Operation: "location", Root: "/local", Account: "../escape"},
		{Operation: "location", Root: "/local", Inputs: []presetfiles.Input{{Root: "/other"}}},
		{Operation: "location", Root: "/local", Picks: []Pick{{Name: "Fixture"}}},
		{Operation: "list", Root: "/local", Account: "account"},
		{Operation: "manifest", Root: "/local", Account: "account"},
	} {
		if _, _, err := marshalRequest(request); err == nil {
			t.Fatal("cross-operation authority accepted")
		}
	}
	local := &presetfiles.LocationInspection{Manifest: presetfiles.BambuManifest{BundleVersion: "1.2.3.4", Machines: []presetfiles.ManifestEntry{}}, UserFiles: []string{}}
	for _, operation := range []string{"list", "manifest", "project"} {
		data, _ := json.Marshal(envelope{Version: 1, Response: Response{Location: local}})
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: operation}); err != Code("worker_response_invalid") {
			t.Fatal("unexpected location result accepted")
		}
	}
	for _, result := range []envelope{
		{Version: 1},
		{Version: 1, Code: "source_unavailable", Response: Response{Location: local}},
		{Version: 1, Response: Response{Location: local, Names: []string{"a.json"}}},
		{Version: 1, Response: Response{Location: local, Manifest: &local.Manifest}},
	} {
		data, _ := json.Marshal(result)
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: "location"}); err != Code("worker_response_invalid") {
			t.Fatal("partial/mixed location frame accepted")
		}
	}
	data, _ := json.Marshal(envelope{Version: 1, Response: Response{Location: local}})
	if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: "location", Account: "chosen"}); err != Code("worker_response_invalid") {
		t.Fatal("missing user inspection accepted")
	}
	public, _ := json.Marshal(Request{Operation: "location", Root: "/private", Account: "private-account"})
	if string(public) != "{}" {
		t.Fatal("JSON serialized local path authority")
	}
}
