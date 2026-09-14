package presetconsent

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/presetui"
)

func TestLocalBrowserOwnedURLAndSingleAttempt(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	h := testHost(t, s, localLimits())
	open := func(ctx context.Context, target string) error {
		if target != h.URL() || !presetui.ValidPreviewURL(target) {
			t.Fatal("unowned URL")
		}
		deadline, ok := ctx.Deadline()
		if !ok || time.Until(deadline) > presetui.BrowserTimeout {
			t.Fatal("launch unbounded")
		}
		return nil
	}
	if err := h.openBrowser(context.Background(), open); err != nil {
		t.Fatal(err)
	}
	if err := h.openBrowser(context.Background(), func(context.Context, string) error { t.Fatal("duplicate launch"); return nil }); err != Code("consent_browser_already_attempted") {
		t.Fatal(err)
	}
	select {
	case <-h.Done():
		t.Fatal("duplicate revoked first launch")
	default:
	}
	if calls.Load() != 0 {
		t.Fatal("launch scanned profiles")
	}
}
func TestLocalBrowserFailureRevokesHost(t *testing.T) {
	for _, mode := range []string{"failure", "cancel", "expired", "nil", "owner-close"} {
		t.Run(mode, func(t *testing.T) {
			var calls atomic.Int32
			s := fixtureSession(t, fakeBackend(&calls))
			h := testHost(t, s, localLimits())
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "expired" {
				cancel()
			}
			if mode == "nil" {
				ctx = nil
			}
			open := func(ctx context.Context, _ string) error {
				if mode == "expired" || mode == "nil" {
					t.Fatal("invalid context launched")
				}
				if mode == "cancel" {
					cancel()
					<-ctx.Done()
					return nil
				}
				if mode == "owner-close" {
					h.cancel()
					<-ctx.Done()
					return nil
				}
				return errors.New("PRIVATE_DIAGNOSTIC")
			}
			if err := h.openBrowser(ctx, open); err != Code("consent_browser_unavailable") {
				t.Fatal("launch failure not redacted")
			}
			waitDone(t, h)
			if calls.Load() != 0 {
				t.Fatal("failed launch scanned profiles")
			}
		})
	}
}
func TestLocalBrowserConcurrentAttempt(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	h := testHost(t, s, localLimits())
	started, release := make(chan struct{}), make(chan struct{})
	result := make(chan error, 1)
	go func() {
		result <- h.openBrowser(context.Background(), func(context.Context, string) error { close(started); <-release; return nil })
	}()
	<-started
	if err := h.openBrowser(context.Background(), nil); err != Code("consent_browser_already_attempted") {
		t.Fatal(err)
	}
	close(release)
	if err := <-result; err != nil {
		t.Fatal(err)
	}
}
