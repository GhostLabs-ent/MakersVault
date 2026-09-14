package presetconsent

import (
	"context"
	"errors"
	"net/http"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/presetui"
	"makersvault/slicer-bridge/internal/presetworker"
)

func pendingPicker(t *testing.T, s *Session) *folderOperation {
	t.Helper()
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.picker == nil {
		t.Fatal("no pending picker")
	}
	return s.picker
}
func pickerFinished(t *testing.T, op *folderOperation) {
	t.Helper()
	select {
	case <-op.done:
	case <-time.After(2 * time.Second):
		t.Fatal("picker did not finish")
	}
}

func TestPickerExplicitAsyncConsentAndConfirmation(t *testing.T) {
	for _, initial := range []string{"consent", "roots"} {
		t.Run(initial, func(t *testing.T) {
			var calls, picks atomic.Int32
			b := fakeBackend(&calls)
			release := make(chan struct{})
			b.pick = func(ctx context.Context) (string, error) {
				picks.Add(1)
				select {
				case <-release:
					return filepath.Join(syntheticRoot(), "private-picked"), nil
				case <-ctx.Done():
					return "", ctx.Err()
				}
			}
			run := b.run
			b.run = func(ctx context.Context, req presetworker.Request) (presetworker.Response, error) {
				if req.Root != filepath.Join(syntheticRoot(), "private-picked") {
					t.Error("selected authority changed")
				}
				return run(ctx, req)
			}
			s := fixtureSession(t, b)
			if initial == "roots" {
				act(t, s, "allow")
			}
			before := calls.Load()
			old := s.View()
			ctx, cancel := context.WithCancel(context.Background())
			if err := s.Apply(ctx, Action{Revision: old.Revision, Decision: "browse"}); err != nil {
				t.Fatal(err)
			}
			op := pendingPicker(t, s)
			cancel() // HTTP return/disconnect must not cancel an accepted dialog
			v := s.View()
			if !v.Busy || !v.Picking || v.Stage != "picking" || len(v.Choices) != 0 || calls.Load() != before || op.ctx.Err() != nil {
				t.Fatal("not asynchronous or read before confirmation")
			}
			if deadline, ok := op.ctx.Deadline(); !ok || time.Until(deadline) > presetui.PickerTimeout {
				t.Fatal("unbounded picker")
			}
			for _, decision := range []string{"browse", "allow", "restart", "choose", "approve"} {
				if err := s.Apply(context.Background(), Action{Revision: v.Revision, Decision: decision}); err != Code("consent_busy") {
					t.Fatal("work queued behind picker")
				}
			}
			close(release)
			pickerFinished(t, op)
			v = s.View()
			if v.Busy || v.Stage != "roots" || len(v.Choices) != 1 || strings.Contains(v.Choices[0].Label, "private-picked") || calls.Load() != before || picks.Load() != 1 {
				t.Fatal("completion read or leaked path")
			}
			if err := s.Apply(context.Background(), Action{Revision: old.Revision, Decision: "browse"}); err != Code("consent_stale") {
				t.Fatal("replayed picker")
			}
			act(t, s, "choose", v.Choices[0].ID)
			if s.View().Stage != "accounts" || calls.Load() != before+1 {
				t.Fatal("confirmation failed")
			}
			act(t, s, "restart")
			if s.root != "" || s.customRoot != "" || len(s.View().Choices) != 0 {
				t.Fatal("restart retained chosen root")
			}
		})
	}
}

func TestPickerCancellationKeepsSlotAndDropsLateSuccess(t *testing.T) {
	var calls atomic.Int32
	b := fakeBackend(&calls)
	release := make(chan struct{})
	var once sync.Once
	t.Cleanup(func() { once.Do(func() { close(release) }) })
	b.pick = func(context.Context) (string, error) { <-release; return syntheticRoot(), nil }
	s := fixtureSession(t, b)
	act(t, s, "allow")
	old := s.View().Choices[0].ID
	act(t, s, "browse")
	op := pendingPicker(t, s)
	act(t, s, "stop-picker")
	if !s.View().Busy || !s.View().PickerStopping {
		t.Fatal("cancel freed slot early")
	}
	if err := s.Apply(context.Background(), Action{Revision: s.View().Revision, Decision: "browse"}); err != Code("consent_busy") {
		t.Fatal("new picker queued")
	}
	once.Do(func() { close(release) })
	pickerFinished(t, op)
	v := s.View()
	if v.Stage != "roots" || v.Busy || !strings.Contains(v.Warning, "cancelled") || len(v.Choices) != 1 || v.Choices[0].ID == old || calls.Load() != 1 {
		t.Fatal("cancel accepted late root or reused ID")
	}
}

func TestPickerOwnerCloseAndExpiryDiscardLateResult(t *testing.T) {
	for _, kind := range []string{"close", "cancel", "expiry", "host"} {
		t.Run(kind, func(t *testing.T) {
			var calls atomic.Int32
			b := fakeBackend(&calls)
			release := make(chan struct{})
			var once sync.Once
			t.Cleanup(func() { once.Do(func() { close(release) }) })
			b.pick = func(context.Context) (string, error) { <-release; return syntheticRoot(), nil }
			s := fixtureSession(t, b)
			if kind == "expiry" {
				s.cancel()
				s.ctx, s.cancel = context.WithTimeout(context.Background(), 100*time.Millisecond)
			}
			h, err := StartLocal(context.Background(), s)
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(h.Close)
			act(t, s, "browse")
			op := pendingPicker(t, s)
			switch kind {
			case "close":
				s.Close()
			case "cancel":
				act(t, s, "cancel")
			case "host":
				h.Close()
			case "expiry":
				<-s.ctx.Done()
			}
			select {
			case <-h.Done():
			case <-time.After(2 * time.Second):
				t.Fatal("owner held open by picker")
			}
			if op.ctx.Err() == nil || s.View().Busy {
				t.Fatal("closed session still offers picker")
			}
			once.Do(func() { close(release) })
			pickerFinished(t, op)
			v := s.View()
			want := "cancelled"
			if kind == "expiry" {
				want = "expired"
			}
			if v.Stage != want || len(v.Choices) != 0 || calls.Load() != 0 {
				t.Fatal("late result revived session")
			}
		})
	}
}

func TestPickerErrorsAndInvalidPathsNeverFallBack(t *testing.T) {
	for _, kind := range []string{"cancel", "timeout", "private-error", "empty", "relative", "unc"} {
		t.Run(kind, func(t *testing.T) {
			var calls atomic.Int32
			b := fakeBackend(&calls)
			release := make(chan struct{})
			b.pick = func(ctx context.Context) (string, error) {
				select {
				case <-release:
				case <-ctx.Done():
					return "", ctx.Err()
				}
				switch kind {
				case "cancel":
					return syntheticRoot(), presetui.Code("ui_cancelled")
				case "timeout":
					return "", presetui.Code("ui_timeout")
				case "private-error":
					return "", errors.New("PRIVATE_DIAGNOSTIC")
				case "relative":
					return "relative/private", nil
				case "unc":
					return `\\server\private`, nil
				}
				return "", nil
			}
			s := fixtureSession(t, b)
			act(t, s, "browse")
			op := pendingPicker(t, s)
			close(release)
			pickerFinished(t, op)
			v := s.View()
			if v.Stage != "roots" || v.Busy || len(v.Choices) != 0 || v.Warning == "" || strings.Contains(v.Warning, "PRIVATE") || calls.Load() != 0 {
				t.Fatal("failed selection read, leaked, or fell back")
			}
		})
	}
}

func TestPickerRejectsUnconsentedStaleAndPathActions(t *testing.T) {
	var calls, picks atomic.Int32
	b := fakeBackend(&calls)
	b.pick = func(context.Context) (string, error) { picks.Add(1); return syntheticRoot(), nil }
	s := fixtureSession(t, b)
	for _, action := range []Action{{Decision: "browse"}, {Revision: s.View().Revision, Decision: "browse", Choices: []string{syntheticRoot()}}, {Revision: s.View().Revision, Decision: "browse", Digest: "x"}, {Revision: s.View().Revision, Decision: "stop-picker"}} {
		if err := s.Apply(context.Background(), action); err == nil {
			t.Fatal("invalid picker action accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := s.Apply(ctx, Action{Revision: s.View().Revision, Decision: "browse"}); err != Code("consent_operation_cancelled") {
		t.Fatal("pre-cancel ignored")
	}
	if err := s.Apply(nil, Action{Revision: s.View().Revision, Decision: "browse"}); err == nil {
		t.Fatal("nil context accepted")
	}
	act(t, s, "allow")
	act(t, s, "choose", s.View().Choices[0].ID)
	if err := s.Apply(context.Background(), Action{Revision: s.View().Revision, Decision: "browse"}); err == nil {
		t.Fatal("wrong-stage browse")
	}
	if picks.Load() != 0 {
		t.Fatal("invalid action launched picker")
	}
	without := fixtureSession(t, fakeBackend(&calls))
	if without.View().CanPick {
		t.Fatal("missing provider offered")
	}
	if err := without.Apply(context.Background(), Action{Revision: without.View().Revision, Decision: "browse"}); err == nil {
		t.Fatal("missing provider accepted")
	}
}

func TestPickerHTTPReturnsBeforeDialogAndRefreshIsReadOnly(t *testing.T) {
	var calls, picks atomic.Int32
	b := fakeBackend(&calls)
	release := make(chan struct{})
	b.pick = func(ctx context.Context) (string, error) {
		picks.Add(1)
		select {
		case <-release:
			return filepath.Join(syntheticRoot(), "PRIVATE_PATH"), nil
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
	s := fixtureSession(t, b)
	h, err := NewLocalHandler(s, "127.0.0.1:43123")
	if err != nil {
		t.Fatal(err)
	}
	if w := serve(h, pageRequest(h, "GET", nil)); w.Code != 200 || picks.Load() != 0 {
		t.Fatal("GET started picker")
	}
	form := pageForm(h, "browse")
	for _, kind := range []string{"path-field", "path-choice", "origin", "csrf"} {
		bad := pageForm(h, "browse")
		r := pageRequest(h, "POST", bad)
		switch kind {
		case "path-field":
			bad.Set("Root", syntheticRoot())
			r = pageRequest(h, "POST", bad)
		case "path-choice":
			bad.Add("choice", syntheticRoot())
			r = pageRequest(h, "POST", bad)
		case "origin":
			r.Header.Set("Origin", "https://vault.example")
		case "csrf":
			bad.Set("csrf", "bad")
			r = pageRequest(h, "POST", bad)
		}
		if serve(h, r).Code < 400 || picks.Load() != 0 {
			t.Fatal("invalid HTTP launched picker")
		}
	}
	request := pageRequest(h, "POST", form)
	ctx, cancel := context.WithCancel(request.Context())
	start := time.Now()
	w := serve(h, request.WithContext(ctx))
	cancel()
	if time.Since(start) > time.Second || w.Code != 200 || !strings.Contains(w.Body.String(), "Refresh status") {
		t.Fatal("dialog blocked HTTP")
	}
	op := pendingPicker(t, s)
	for i := 0; i < 3; i++ {
		if w := serve(h, pageRequest(h, "GET", nil)); w.Code != 200 || !strings.Contains(w.Body.String(), `href="`+h.path+`"`) || strings.Contains(w.Body.String(), "http-equiv") {
			t.Fatal("invalid refresh")
		}
	}
	if serve(h, pageRequest(h, "POST", form)).Code != 409 {
		t.Fatal("HTTP replay accepted")
	}
	close(release)
	pickerFinished(t, op)
	w = serve(h, pageRequest(h, http.MethodGet, nil))
	if strings.Contains(w.Body.String(), "PRIVATE_PATH") || strings.Contains(w.Body.String(), "checked") || picks.Load() != 1 || calls.Load() != 0 || !strings.Contains(w.Body.String(), "Use this folder") {
		t.Fatal("path disclosed or unconfirmed read")
	}
}
