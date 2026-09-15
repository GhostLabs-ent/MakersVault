//go:build makersvault_native_qualification

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"

	"makersvault/slicer-bridge/internal/presetconsent"
	"makersvault/slicer-bridge/internal/presetui"
	"makersvault/slicer-bridge/internal/presetworker"
)

func TestQualificationCommandRequiresExactConsent(t *testing.T) {
	if code := command([]string{"--ui-fixture"}, strings.NewReader("START UI TEST\n"), brokenOutput{}, true, func(io.Writer) int { t.Fatal("unshown notice launched UI"); return 0 }); code != 1 {
		t.Fatal("broken notice output accepted")
	}
	for _, input := range []string{"", "START UI TEST", "yes\n", " START UI TEST\n", "START UI TEST \n", strings.Repeat("x", 256) + "\n"} {
		var out bytes.Buffer
		code := command([]string{"--ui-fixture"}, strings.NewReader(input), &out, true, func(io.Writer) int { t.Fatal("invalid consent launched UI"); return 0 })
		if code != 2 {
			t.Fatal("invalid input accepted")
		}
	}
	for _, input := range []string{"START UI TEST\n", "START UI TEST\r\n"} {
		var out bytes.Buffer
		called := false
		if code := command([]string{"--ui-fixture"}, strings.NewReader(input), &out, true, func(io.Writer) int { called = true; return 7 }); code != 7 || !called {
			t.Fatal("explicit consent not forwarded")
		}
	}
}

type brokenOutput struct{}

func (brokenOutput) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

func TestQualificationCommandRejectsExtraAuthority(t *testing.T) {
	for _, args := range [][]string{nil, {"--ui-fixture", "/private"}, {"--ui-fixture", "https://vault.example"}, {"--inspect", "--ui-fixture"}, {presetworker.Argument}, {presetui.Argument}, {"--install"}, {"--unknown"}} {
		var out bytes.Buffer
		if command(args, strings.NewReader("START UI TEST\n"), &out, true, func(io.Writer) int { t.Fatal("invalid command launched UI"); return 0 }) != 2 {
			t.Fatal("invalid command accepted")
		}
		if strings.Contains(out.String(), "/private") || strings.Contains(out.String(), "vault.example") {
			t.Fatal("raw argument echoed")
		}
	}
	var out bytes.Buffer
	if command([]string{"--ui-fixture"}, strings.NewReader("START UI TEST\n"), &out, false, func(io.Writer) int { t.Fatal("redirected input launched UI"); return 0 }) != 2 {
		t.Fatal("noninteractive mode accepted")
	}
}

func TestQualificationInspectIsNotNativeEvidence(t *testing.T) {
	var out bytes.Buffer
	if command([]string{"--inspect"}, nil, &out, false, func(io.Writer) int { t.Fatal("inspect launched UI"); return 0 }) != 0 {
		t.Fatal("inspect failed")
	}
	var row receipt
	if json.Unmarshal(out.Bytes(), &row) != nil || row.Outcome != "inspection_only_no_native_ui" || row.GateQualified || row.BrowserAccepted || row.ReviewSHA256 != "" {
		t.Fatal("inspection overclaims")
	}
}

type fakeOwner struct {
	done                 chan struct{}
	once                 sync.Once
	stage                string
	launchErr, errorTake error
	viewText             string
	closed               bool
}

func (o *fakeOwner) OpenBrowser(context.Context) error { return o.launchErr }
func (o *fakeOwner) Close()                            { o.once.Do(func() { o.closed = true; close(o.done) }) }
func (o *fakeOwner) Done() <-chan struct{}             { return o.done }
func (o *fakeOwner) View() presetconsent.View {
	return presetconsent.View{Stage: o.stage, Preview: o.viewText}
}
func (o *fakeOwner) TakeApproved() ([]byte, error) { return []byte("synthetic-only"), o.errorTake }

func TestQualificationOwnerClosesAndRedactsFailures(t *testing.T) {
	for _, kind := range []string{"launch", "approval", "expired", "cancelled", "unrecognized-stage", "success"} {
		t.Run(kind, func(t *testing.T) {
			o := &fakeOwner{done: make(chan struct{}), stage: "approved", viewText: "PRIVATE_PATH_OR_PREVIEW"}
			switch kind {
			case "launch":
				o.launchErr = errors.New("PRIVATE_ERROR")
			case "approval":
				o.errorTake = errors.New("PRIVATE_ERROR")
			case "expired", "cancelled", "unrecognized-stage":
				o.stage = kind
				o.Close()
			}
			var out bytes.Buffer
			code := runSession(context.Background(), &out, func(context.Context) (owner, error) { return o, nil })
			if !o.closed {
				t.Fatal("owner not closed")
			}
			if (kind == "launch" || kind == "approval") != (code == 1) {
				t.Fatal("incorrect failure status")
			}
			if strings.Contains(out.String(), "PRIVATE") {
				t.Fatal("private diagnostics leaked")
			}
			var row receipt
			if json.Unmarshal(out.Bytes(), &row) != nil || row.GateQualified {
				t.Fatal("overclaimed or malformed result")
			}
			if kind == "success" && (row.Outcome != "synthetic_preview_consumed" || len(row.ReviewSHA256) != 64) {
				t.Fatal("missing synthetic consumption")
			}
		})
	}
}

func TestQualificationPrecancelAndUnavailable(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	for _, ctx := range []context.Context{nil, ctx} {
		var out bytes.Buffer
		if runSession(ctx, &out, func(context.Context) (owner, error) { t.Fatal("cancelled owner started"); return nil, nil }) != 1 {
			t.Fatal("cancel ignored")
		}
	}
	var out bytes.Buffer
	if runSession(context.Background(), &out, func(context.Context) (owner, error) { return nil, errors.New("PRIVATE") }) != 1 || strings.Contains(out.String(), "PRIVATE") {
		t.Fatal("unavailable owner failed open")
	}
}

func TestQualificationLocalOwnerWithoutNativeLaunch(t *testing.T) {
	o, err := newOwner(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if o.View().Stage != "consent" || !o.View().CanPick {
		t.Fatal("initial qualification state invalid")
	}
	o.Close()
	<-o.Done()
	if o.View().Stage != "cancelled" {
		t.Fatal("owner did not revoke session")
	}
}

func FuzzQualificationConsent(f *testing.F) {
	for _, seed := range []string{"START UI TEST\n", "START UI TEST\r\n", "no\n"} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, input string) {
		if len(input) > 1024 {
			return
		}
		called := false
		code := command([]string{"--ui-fixture"}, strings.NewReader(input), io.Discard, true, func(io.Writer) int { called = true; return 0 })
		valid := strings.HasPrefix(input, "START UI TEST\n") || strings.HasPrefix(input, "START UI TEST\r\n")
		if called != valid || (code == 0) != valid {
			t.Fatal("consent parser disagreement")
		}
	})
}
