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

func TestWorkerSavedUserRoundTripAndAtomicFailure(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		t.Skip("Windows/Linux content reader only")
	}
	root := t.TempDir()
	for _, relative := range []string{"system/BBL/machine", "user/private-account/machine"} {
		if err := os.MkdirAll(filepath.Join(root, relative), 0700); err != nil {
			t.Fatal(err)
		}
	}
	files := map[string]string{
		"system/BBL.json": `{"name":"Bambulab","version":"1.2.3.4","machine_list":[]}`,
		"user/private-account/machine/local-file.json": `{"name":"Saved machine","from":"User","version":"2.8.2.61","printhost_apikey":"PRIVATE_KEY"}`,
	}
	for file, data := range files {
		if err := os.WriteFile(filepath.Join(root, file), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	result, err := Run(context.Background(), Request{Operation: "discover", Root: root, Account: "private-account"})
	if err != nil || result.Discovery == nil || len(result.Discovery.Selections) != 1 {
		t.Fatal(result, err)
	}
	picks := result.Discovery.Selections
	result, err = Run(context.Background(), Request{Operation: "select", Root: root, Account: "private-account", Picks: picks})
	if err != nil || len(result.Candidates) != 1 || result.Candidates[0].Complete() || len(result.Candidates[0].Reasons) == 0 {
		t.Fatal(result, err)
	}
	data, _ := json.Marshal(result)
	for _, private := range []string{root, "private-account", "local-file.json", "2.8.2.61", "PRIVATE_KEY"} {
		if strings.Contains(string(data), private) {
			t.Fatal("worker privacy failure")
		}
	}
	input := presetfiles.Input{Root: filepath.Join(root, "user/private-account/machine"), Files: []string{"local-file.json"}, Source: printerpreset.Source{Namespace: "local", Kind: printerpreset.User}}
	if result, err := Run(context.Background(), Request{Operation: "project", Inputs: []presetfiles.Input{input}, Picks: picks}); len(result.Candidates) != 0 || err != Code("invalid_machine_identity") {
		t.Fatal("generic worker relaxed", err)
	}
	if err := os.WriteFile(filepath.Join(input.Root, "bad.json"), []byte(`{"name":"Bad","from":"User","version":"PRIVATE_BAD_VERSION"}`), 0600); err != nil {
		t.Fatal(err)
	}
	for _, op := range []string{"discover", "select"} {
		request := Request{Operation: op, Root: root, Account: "private-account"}
		if op == "select" {
			request.Picks = picks
		}
		result, err := Run(context.Background(), request)
		if result.Discovery != nil || len(result.Candidates) != 0 || err != Code("unsupported_user_version") {
			t.Fatal("partial/malformed user scan", err)
		}
	}
}

func TestWorkerRejectsUserFormatAuthorityInWire(t *testing.T) {
	var request wireRequest
	if err := decode([]byte(`{"Version":1,"Operation":"project","LocalUserMachine":true}`), &request); err != Code("worker_frame_invalid") {
		t.Fatal("wire acquired format authority", err)
	}
}
