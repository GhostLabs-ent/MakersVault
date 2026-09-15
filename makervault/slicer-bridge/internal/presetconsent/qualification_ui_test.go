//go:build makersvault_native_qualification

package presetconsent

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"makersvault/slicer-bridge/internal/presetworker"
	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestUIQualificationSyntheticSession(t *testing.T) {
	s, err := NewUIQualification(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if s.View().Origin != "https://qualification.invalid" || !s.View().CanPick {
		t.Fatal("incorrect qualification scope")
	}
	toReview(t, s) // no browse/native calls: all metadata is in-memory
	v := s.View()
	if !strings.Contains(v.Preview, qualificationName) || strings.Contains(v.Preview, "synthetic-account") || strings.Contains(v.Preview, "makersvault-synthetic-ui-test") {
		t.Fatal("fixture identity or privacy failed")
	}
	var candidates []printerpreset.Candidate
	if json.Unmarshal([]byte(v.Preview), &candidates) != nil || len(candidates) != 1 || candidates[0].SchemaVersion != 1 || len(candidates[0].Fingerprint) != 64 || candidates[0].Source.ApplicationVersion != "" {
		t.Fatal("invalid normalized fixture")
	}
	if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "approve", Digest: v.Digest}); err != nil {
		t.Fatal(err)
	}
	if data, err := s.TakeApproved(); err != nil || string(data) != v.Preview {
		t.Fatal("fixture consumption changed bytes")
	}
}

func TestUIQualificationIgnoresFilesystemAuthority(t *testing.T) {
	// Invalid/nonexistent roots and accounts cannot trigger filesystem work or
	// leak through the synthetic response; no file worker is called at all.
	for _, operation := range []string{"accounts", "discover", "select"} {
		for _, root := range []string{"/DO_NOT_READ/private", `\\remote\DO_NOT_READ`, "\x00"} {
			request := presetworker.Request{Operation: operation, Root: root, Account: "PRIVATE_ACCOUNT", Picks: []printerpreset.Selection{{Kind: printerpreset.System, Name: qualificationName}}}
			response, err := qualificationMetadata(context.Background(), request)
			if err != nil {
				t.Fatal(err)
			}
			data, err := json.Marshal(response)
			if err != nil || strings.Contains(string(data), "PRIVATE_ACCOUNT") || strings.Contains(string(data), "DO_NOT_READ") {
				t.Fatal("synthetic response used source authority")
			}
		}
	}
}

func TestUIQualificationRejectsInvalidWork(t *testing.T) {
	for _, request := range []presetworker.Request{{Operation: "native-locations"}, {Operation: "project"}, {Operation: "select"}, {Operation: "select", Picks: []printerpreset.Selection{{Kind: printerpreset.User, Name: qualificationName}}}} {
		if _, err := qualificationMetadata(context.Background(), request); err == nil {
			t.Fatal("unsupported qualification operation")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := qualificationMetadata(ctx, presetworker.Request{Operation: "accounts"}); err == nil {
		t.Fatal("cancel ignored")
	}
	if s, err := NewUIQualification(nil); s != nil || err == nil {
		t.Fatal("nil context accepted")
	}
}
