package presetworker

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"makersvault/slicer-bridge/internal/presetfiles"
)

func TestWorkerAccountChoicesRoundTrip(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		t.Skip("account listing is Windows/Linux only")
	}
	root := t.TempDir()
	for _, name := range []string{"default", "private-account"} {
		if err := os.MkdirAll(filepath.Join(root, "user", name, "machine"), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, "user", name, "machine", "invalid.json"), []byte("PRIVATE_BODY_NOT_READ"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("MAKERSVAULT_PARENT_SECRET", "SYNTHETIC_SECRET")
	t.Setenv("XDG_CONFIG_HOME", "/unrelated-parent-config")
	response, err := Run(context.Background(), Request{Operation: "accounts", Root: root})
	if err != nil || response.Accounts == nil || !response.Accounts.Validate() ||
		!reflect.DeepEqual(response.Accounts.Names, []string{"default", "private-account"}) {
		t.Fatalf("local account listing rejected: %v", err)
	}
	data, _ := json.Marshal(response)
	for _, private := range []string{root, "PRIVATE_BODY_NOT_READ", "SYNTHETIC_SECRET", "/unrelated-parent-config"} {
		if strings.Contains(string(data), private) {
			t.Fatal("private body/environment/root crossed account response")
		}
	}
	// Successful names are deliberately private picker data, never candidates.
	if len(response.Candidates) != 0 || response.Discovery != nil || response.Location != nil {
		t.Fatal("listing made implicit selection")
	}
	if err := os.Rename(filepath.Join(root, "user"), filepath.Join(root, "moved-user")); err != nil {
		t.Fatal(err)
	}
	response, err = Run(context.Background(), Request{Operation: "accounts", Root: root})
	if err != Code("source_unavailable") || !reflect.DeepEqual(response, Response{}) {
		t.Fatal("missing listing yielded partial choices or native hint fallback")
	}
}

func TestWorkerAccountsCannotCarrySelectionAuthority(t *testing.T) {
	for _, request := range []Request{
		{Operation: "accounts"},
		{Operation: "accounts", Root: "/local", Account: "default"},
		{Operation: "accounts", Root: "/local", Picks: []Pick{{Name: "Fixture"}}},
		{Operation: "accounts", Root: "/local", Inputs: []presetfiles.Input{{Root: "/other"}}},
		{Operation: "native-hints", Root: "/local"},
	} {
		if _, _, err := marshalRequest(request); err == nil {
			t.Fatal("cross-operation authority accepted")
		}
	}
	public, _ := json.Marshal(Request{Operation: "accounts", Root: "/local", Account: "private"})
	if string(public) != "{}" {
		t.Fatal("public JSON serialized filesystem authority")
	}
	var decoded Request
	if err := json.Unmarshal([]byte(`{"Operation":"accounts","Root":"/private"}`), &decoded); err != nil || decoded.Root != "" || decoded.Operation != "" {
		t.Fatal("public JSON acquired filesystem authority")
	}
	for _, frame := range []string{
		`{"Version":1,"Operation":"accounts","Root":"/local","Account":"default"}`,
		`{"Version":1,"Operation":"accounts","Root":"/local","Hints":{"ConfigHome":"/private"}}`,
		`{"Version":1,"Operation":"accounts","Root":"/local","Selected":true}`,
	} {
		var output bytes.Buffer
		if Serve(strings.NewReader(frame), &output) != 0 {
			t.Fatal("private frame write failed")
		}
		var result envelope
		if json.Unmarshal(output.Bytes(), &result) != nil || result.Code != "worker_request_invalid" || !reflect.DeepEqual(result.Response, Response{}) {
			t.Fatal("wire acquired hint/selection authority")
		}
	}
}

func TestWorkerAccountResponseIsStrictAndLocalOnly(t *testing.T) {
	valid := &presetfiles.AccountChoices{Names: []string{"default", "private-account"}}
	for _, operation := range []string{"list", "manifest", "location", "discover", "select", "project"} {
		data, _ := json.Marshal(envelope{Version: 1, Response: Response{Accounts: valid}})
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: operation}); err != Code("worker_response_invalid") {
			t.Fatal("account names crossed another operation")
		}
	}
	for _, result := range []envelope{
		{Version: 1},
		{Version: 1, Code: "source_unavailable", Response: Response{Accounts: valid}},
		{Version: 1, Response: Response{Accounts: valid, Names: []string{"a.json"}}},
		{Version: 1, Response: Response{Accounts: valid, Discovery: &presetfiles.BambuDiscovery{}}},
		{Version: 1, Response: Response{Accounts: valid, Location: &presetfiles.LocationInspection{}}},
		{Version: 1, Response: Response{Accounts: valid, Manifest: &presetfiles.BambuManifest{}}},
		{Version: 1, Response: Response{Accounts: &presetfiles.AccountChoices{Names: nil}}},
		{Version: 1, Response: Response{Accounts: &presetfiles.AccountChoices{Names: []string{"A", "a"}}}},
		{Version: 1, Response: Response{Accounts: &presetfiles.AccountChoices{Names: []string{".."}}}},
	} {
		data, _ := json.Marshal(result)
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: "accounts"}); err != Code("worker_response_invalid") {
			t.Fatal("partial/mixed/invalid account response accepted")
		}
	}
	for _, frame := range []string{
		`{"Version":1,"Response":{"accounts":{"names":[],"selected":"default"}}}`,
		`{"Version":1,"Response":{"accounts":{"names":[],"NAMES":["default"]}}}`,
		`{"Version":1,"Response":{"accounts":{"names":[],"root":"/private"}}}`,
	} {
		if _, err := decodeResponse([]byte(frame), wireRequest{Version: 1, Operation: "accounts"}); err != Code("worker_response_invalid") {
			t.Fatal("unexpected account response fields accepted")
		}
	}
}
