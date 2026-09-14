package presetconsent

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/presetfiles"
	"makersvault/slicer-bridge/internal/presetui"
	"makersvault/slicer-bridge/internal/presetworker"
	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestMain(m *testing.M) {
	if len(os.Args) == 2 && os.Args[1] == presetui.Argument {
		os.Exit(31) // tests must never dispatch a real desktop UI
	}
	if len(os.Args) == 2 && os.Args[1] == "--local-picker-fixture" {
		os.Exit(servePickerFixture())
	}
	if len(os.Args) == 2 && os.Args[1] == "--local-http-fixture" {
		os.Exit(serveBrowserFixture())
	}
	if len(os.Args) == 2 && os.Args[1] == presetworker.Argument {
		os.Exit(presetworker.Serve(os.Stdin, os.Stdout))
	}
	os.Exit(m.Run())
}

func config() Config {
	return Config{Origin: "https://vault.example", ExpiresAt: time.Now().Add(time.Minute)}
}
func syntheticRoot() string {
	if runtime.GOOS == "windows" {
		return `C:\synthetic`
	}
	return "/synthetic"
}
func fakeBackend(calls *atomic.Int32) backend {
	return backend{
		hints: func(context.Context) ([]presetfiles.BambuLocation, error) {
			calls.Add(1)
			return []presetfiles.BambuLocation{{ID: "BambuStudio", DataRoot: syntheticRoot()}}, nil
		},
		run: func(ctx context.Context, req presetworker.Request) (presetworker.Response, error) {
			calls.Add(1)
			switch req.Operation {
			case "accounts":
				return presetworker.Response{Accounts: &presetfiles.AccountChoices{Names: []string{"default", "private-account"}}}, nil
			case "discover":
				return presetworker.Response{Discovery: &presetfiles.BambuDiscovery{BundleVersion: "1.2.3.4", UserIncluded: req.Account != "", Selections: []printerpreset.Selection{{Kind: printerpreset.System, Name: "Fixture"}}}}, nil
			case "select":
				return presetworker.Response{Candidates: []printerpreset.Candidate{{Source: printerpreset.Identity{Kind: printerpreset.System, Name: "Fixture"}}}}, nil
			}
			return presetworker.Response{}, errors.New("PRIVATE_BACKEND_ERROR")
		},
	}
}
func fixtureSession(t *testing.T, runner backend) *Session {
	t.Helper()
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		t.Skip("new local import is Windows/Linux only")
	}
	s, err := newSession(context.Background(), config(), runner)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(s.Close)
	return s
}
func act(t *testing.T, s *Session, decision string, choices ...string) {
	t.Helper()
	v := s.View()
	if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: decision, Choices: choices}); err != nil {
		t.Fatal(err)
	}
}
func toReview(t *testing.T, s *Session) {
	t.Helper()
	act(t, s, "allow")
	act(t, s, "choose", s.View().Choices[0].ID)
	act(t, s, "choose", s.View().Choices[0].ID)
	act(t, s, "preview", s.View().Choices[0].ID)
}

func TestConsentNoReadBeforeApprovalAndExplicitChoices(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	initial := s.View()
	if initial.Stage != "consent" || len(initial.Choices) != 0 || calls.Load() != 0 {
		t.Fatal("constructor/view performed discovery")
	}
	if _, err := s.TakeApproved(); err == nil {
		t.Fatal("unapproved result escaped")
	}
	if err := s.Apply(context.Background(), Action{Revision: initial.Revision, Decision: "choose", Choices: []string{"default"}}); err == nil || calls.Load() != 0 {
		t.Fatal("selection preceded consent")
	}
	act(t, s, "allow")
	v := s.View()
	if v.Stage != "roots" || calls.Load() != 1 || v.Choices[0].ID == syntheticRoot() {
		t.Fatal("root authority not opaque")
	}
	if err := s.Apply(context.Background(), Action{Revision: initial.Revision, Decision: "allow"}); err != Code("consent_stale") {
		t.Fatal("stale consent replayed")
	}
	act(t, s, "choose", v.Choices[0].ID)
	v = s.View()
	if v.Stage != "accounts" || len(v.Choices) != 3 || calls.Load() != 2 {
		t.Fatal("account automatically chosen")
	}
	for _, value := range []string{"", "default", "private-account", syntheticRoot()} {
		if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "choose", Choices: []string{value}}); err == nil {
			t.Fatal("raw name/path became choice authority")
		}
	}
	act(t, s, "choose", v.Choices[2].ID)
	if s.View().Stage != "presets" || calls.Load() != 3 {
		t.Fatal("account choice failed")
	}
}

func TestConsentReviewDigestOneShotAndCopy(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	toReview(t, s)
	v := s.View()
	if v.Stage != "review" || v.Preview == "" || len(v.Digest) != 64 || calls.Load() != 4 {
		t.Fatal("missing exact review")
	}
	for _, invalid := range []Action{{Revision: v.Revision, Decision: "approve"}, {Revision: v.Revision, Decision: "approve", Digest: strings.Repeat("0", 64)}, {Revision: "stale", Decision: "approve", Digest: v.Digest}} {
		if err := s.Apply(context.Background(), invalid); err == nil {
			t.Fatal("unreviewed bytes approved")
		}
	}
	if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "approve", Digest: v.Digest}); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 4 {
		t.Fatal("approval silently rescanned/shared")
	}
	data, err := s.TakeApproved()
	if err != nil || string(data) != v.Preview {
		t.Fatal("consumed different bytes")
	}
	data[0] = 'x'
	if other, err := s.TakeApproved(); other != nil || err == nil {
		t.Fatal("approved preview replayed")
	}
	if s.View().Preview != "" || len(s.View().Choices) != 0 {
		t.Fatal("consumed data retained in view")
	}
}

func TestConsentRestartInvalidatesOldChoicesAndReview(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	act(t, s, "allow")
	old := s.View()
	act(t, s, "restart")
	act(t, s, "allow")
	current := s.View()
	if current.Choices[0].ID == old.Choices[0].ID {
		t.Fatal("reused local choice ID")
	}
	if err := s.Apply(context.Background(), Action{Revision: current.Revision, Decision: "choose", Choices: []string{old.Choices[0].ID}}); err == nil {
		t.Fatal("stale choice remained authorized")
	}
	act(t, s, "restart")
	toReview(t, s)
	act(t, s, "restart")
	if result, err := s.TakeApproved(); result != nil || err == nil || s.View().Preview != "" {
		t.Fatal("restart retained review authority")
	}
}

func TestConsentAccountFailureDoesNotChooseSystem(t *testing.T) {
	var calls atomic.Int32
	runner := fakeBackend(&calls)
	runner.run = func(context.Context, presetworker.Request) (presetworker.Response, error) {
		calls.Add(1)
		return presetworker.Response{}, errors.New("PRIVATE_PATH_CREDENTIAL")
	}
	s := fixtureSession(t, runner)
	act(t, s, "allow")
	act(t, s, "choose", s.View().Choices[0].ID)
	v := s.View()
	if v.Stage != "accounts" || len(v.Choices) != 1 || v.Warning == "" || calls.Load() != 2 {
		t.Fatal("failed listing chose a fallback")
	}
	if strings.Contains(v.Warning, "PRIVATE") {
		t.Fatal("backend diagnostic leaked")
	}
	if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "choose", Choices: []string{v.Choices[0].ID}}); err != Code("consent_source_failed") {
		t.Fatal(err)
	}
	if s.View().Stage != "failed" || s.View().Preview != "" {
		t.Fatal("failed discovery produced partial review")
	}
}

func TestConsentCancelInflightRejectsLateCompletion(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	var calls atomic.Int32
	runner := fakeBackend(&calls)
	runner.hints = func(context.Context) ([]presetfiles.BambuLocation, error) {
		close(started)
		<-release
		return []presetfiles.BambuLocation{{ID: "BambuStudio", DataRoot: syntheticRoot()}}, nil
	}
	s := fixtureSession(t, runner)
	done := make(chan error, 1)
	v := s.View()
	go func() { done <- s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "allow"}) }()
	<-started
	if !s.View().Busy {
		t.Fatal("inflight not visible")
	}
	if err := s.Apply(context.Background(), Action{Revision: s.View().Revision, Decision: "allow"}); err != Code("consent_busy") {
		t.Fatal("overlapping scan allowed")
	}
	s.Close()
	close(release)
	if err := <-done; err != Code("consent_closed") {
		t.Fatal(err)
	}
	if s.View().Stage != "cancelled" || len(s.View().Choices) != 0 {
		t.Fatal("late result resurrected consent")
	}
}

func TestConsentExpiryAndCallerCancellation(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := s.Apply(ctx, Action{Revision: s.View().Revision, Decision: "allow"}); err != Code("consent_operation_cancelled") || calls.Load() != 0 {
		t.Fatal("cancelled request scanned")
	}
	// Inject an already-expired session context; no sleeps or wall-clock race.
	s.cancel()
	s.ctx, s.cancel = context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	if s.View().Stage != "expired" {
		t.Fatal("expiry not enforced")
	}
	if err := s.Apply(context.Background(), Action{Revision: s.View().Revision, Decision: "allow"}); err != Code("consent_closed") {
		t.Fatal("expired consent revived")
	}
	if data, err := s.TakeApproved(); data != nil || err == nil {
		t.Fatal("expired bytes escaped")
	}
}

func TestConsentConfigurationAndCustomRoot(t *testing.T) {
	var calls atomic.Int32
	runner := fakeBackend(&calls)
	for _, origin := range []string{"http://vault.example", "https://user:pass@vault.example", "https://vault.example/path", "https://vault.example?x=1", "https://vault.example?", "https://vault.example:", "https://vault.example#private", "https://VAULT.example"} {
		cfg := config()
		cfg.Origin = origin
		if s, err := newSession(context.Background(), cfg, runner); s != nil || err == nil {
			t.Fatal("invalid origin binding")
		}
	}
	for _, expiry := range []time.Time{{}, time.Now().Add(-time.Second), time.Now().Add(6 * time.Minute)} {
		cfg := config()
		cfg.ExpiresAt = expiry
		if s, err := newSession(context.Background(), cfg, runner); s != nil || err == nil {
			t.Fatal("unbounded session")
		}
	}
	if runtime.GOOS != "windows" && runtime.GOOS != "linux" {
		return
	}
	cfg := config()
	cfg.CustomRoot = syntheticRoot()
	s, err := newSession(context.Background(), cfg, runner)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	act(t, s, "allow")
	if calls.Load() != 0 || len(s.View().Choices) != 1 {
		t.Fatal("explicit custom root triggered native lookup")
	}
	data, _ := json.Marshal(cfg)
	if string(data) != "{}" {
		t.Fatal("config exposes path authority")
	}
}

func TestConsentRealWorkerSyntheticLayout(t *testing.T) {
	if runtime.GOOS != "windows" && runtime.GOOS != "linux" {
		t.Skip("Windows/Linux only")
	}
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "system", "BBL", "machine"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, "user"), 0700); err != nil {
		t.Fatal(err)
	}
	manifest := `{"name":"Bambulab","version":"1.2.3.4","machine_list":[{"name":"Fixture","sub_path":"machine/fixture.json"}]}`
	machine := `{"type":"machine","name":"Fixture","instantiation":"true","printable_area":["0x0","200x0","200x200","0x200"],"printable_height":"200","nozzle_diameter":["0.4"],"bed_exclude_area":[],"secret":"PRIVATE_NOT_SHARED"}`
	for name, data := range map[string]string{filepath.Join("system", "BBL.json"): manifest, filepath.Join("system", "BBL", "machine", "fixture.json"): machine} {
		if err := os.WriteFile(filepath.Join(root, name), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	cfg := config()
	cfg.CustomRoot = root
	s, err := New(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	toReview(t, s)
	v := s.View()
	if strings.Contains(v.Preview, root) || strings.Contains(v.Preview, "PRIVATE_NOT_SHARED") {
		t.Fatal("private source leaked")
	}
	var candidates []printerpreset.Candidate
	if json.Unmarshal([]byte(v.Preview), &candidates) != nil || len(candidates) != 1 || candidates[0].Source.Name != "Fixture" {
		t.Fatal("worker projection did not reach review")
	}
	if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "approve", Digest: v.Digest}); err != nil {
		t.Fatal(err)
	}
	if data, err := s.TakeApproved(); err != nil || string(data) != v.Preview {
		t.Fatal("exact projected review lost")
	}
}

func TestConsentApprovedDataCanStillBeRevoked(t *testing.T) {
	for _, expiry := range []bool{false, true} {
		var calls atomic.Int32
		s := fixtureSession(t, fakeBackend(&calls))
		toReview(t, s)
		v := s.View()
		if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "approve", Digest: v.Digest}); err != nil {
			t.Fatal(err)
		}
		if expiry {
			s.cancel()
			s.ctx, s.cancel = context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
		} else {
			s.Close()
		}
		if data, err := s.TakeApproved(); data != nil || err == nil {
			t.Fatal("revoked/expired approval escaped")
		}
		if s.View().Preview != "" || len(s.View().Choices) != 0 {
			t.Fatal("revoked view retained private data")
		}
	}
}

func TestConsentSelectionLimitsAndChangedSource(t *testing.T) {
	var calls atomic.Int32
	runner := fakeBackend(&calls)
	original := runner.run
	runner.run = func(ctx context.Context, req presetworker.Request) (presetworker.Response, error) {
		if req.Operation == "select" {
			calls.Add(1)
			return presetworker.Response{}, presetworker.Code("preset_not_found")
		}
		return original(ctx, req)
	}
	s := fixtureSession(t, runner)
	act(t, s, "allow")
	act(t, s, "choose", s.View().Choices[0].ID)
	act(t, s, "choose", s.View().Choices[0].ID)
	v := s.View()
	id := v.Choices[0].ID
	for _, ids := range [][]string{nil, {id, id}, make([]string, 101)} {
		if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "preview", Choices: ids}); err != Code("consent_action_invalid") {
			t.Fatal("invalid selection accepted")
		}
	}
	if calls.Load() != 3 {
		t.Fatal("invalid choices performed a scan")
	}
	if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: "preview", Choices: []string{id}}); err != Code("consent_source_failed") {
		t.Fatal(err)
	}
	if s.View().Stage != "failed" || s.View().Preview != "" {
		t.Fatal("discovery substituted for fresh failed selection")
	}
}
