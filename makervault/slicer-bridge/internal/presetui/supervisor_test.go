package presetui

import (
	"bytes"
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Tests NEVER dispatch a real native UI, including when run on Windows.
var nativeFixture func(string)

func TestMain(m *testing.M) {
	if len(os.Args) == 2 && os.Args[1] == Argument {
		os.Exit(31)
	}
	if len(os.Args) == 2 && strings.HasPrefix(os.Args[1], "--fixture-") {
		mode := strings.TrimPrefix(os.Args[1], "--fixture-")
		if nativeFixture != nil {
			nativeFixture(mode)
		}
		hang := func() {
			for {
				time.Sleep(time.Hour)
			}
		}
		if mode == "hang" || mode == "blocked-stdin" {
			hang()
		}
		_, _ = io.Copy(io.Discard, os.Stdin)
		switch mode {
		case "native-cancel":
			os.Stdout.WriteString("/private/partial\n")
			os.Exit(1)
		case "native-cancel-diagnostic":
			os.Stderr.WriteString("PRIVATE_DIAGNOSTIC")
			os.Exit(1)
		case "native-folder":
			os.Stdout.WriteString("/home/fixture/Bambu Studio\n")
			os.Exit(0)
		case "stdout-overflow":
			_, _ = os.Stdout.Write(bytes.Repeat([]byte("x"), MaxResponseBytes+1))
			hang()
		case "stderr-overflow":
			_, _ = os.Stderr.Write(bytes.Repeat([]byte("x"), MaxStderrBytes+1))
			hang()
		case "stderr-private":
			_, _ = os.Stderr.WriteString("PRIVATE_DIAGNOSTIC")
			os.Exit(0)
		case "failed":
			_, _ = os.Stdout.WriteString(`{"Version":1}`)
			os.Exit(7)
		case "malformed":
			_, _ = os.Stdout.WriteString(`{"Version":`)
			os.Exit(0)
		case "echo":
			_, _ = os.Stdout.WriteString(`{"Version":1}`)
			os.Exit(0)
		}
		os.Exit(17)
	}
	os.Exit(m.Run())
}
func fixtureCommand(t *testing.T, mode string) *exec.Cmd {
	t.Helper()
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(self, "--fixture-"+mode)
	cmd.Env = uiEnvironment("windows", os.Getenv)
	return cmd
}
func waitIdle(t *testing.T) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for len(uiSlot) != 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if len(uiSlot) != 0 {
		t.Fatal("ordinary UI child not reaped; slot retained")
	}
}
func TestUIStopsHungAndBlockedInput(t *testing.T) {
	for _, mode := range []string{"hang", "blocked-stdin"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
			defer cancel()
			start := time.Now()
			// Deliberately larger than production input to exercise a blocked pipe writer.
			data, err := supervise(ctx, fixtureCommand(t, mode), bytes.Repeat([]byte("x"), 1<<20))
			if data != nil || err != Code("ui_timeout") || time.Since(start) > 2*time.Second {
				t.Fatal("timeout boundary failed")
			}
			waitIdle(t)
		})
	}
}
func TestUICancellationAndBusySlot(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	cmd := fixtureCommand(t, "hang")
	go func() { _, err := supervise(ctx, cmd, nil); result <- err }()
	deadline := time.Now().Add(2 * time.Second)
	for len(uiSlot) == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if len(uiSlot) == 0 {
		t.Fatal("child not started")
	}
	if data, err := supervise(context.Background(), fixtureCommand(t, "echo"), nil); data != nil || err != Code("ui_busy") {
		t.Fatal("concurrent helper admitted")
	}
	cancel()
	select {
	case err := <-result:
		if err != Code("ui_cancelled") {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("cancel stalled")
	}
	waitIdle(t)
}
func TestUIOutputBudgetsAndRedaction(t *testing.T) {
	for _, mode := range []string{"stdout-overflow", "stderr-overflow", "stderr-private", "failed"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			data, err := supervise(ctx, fixtureCommand(t, mode), nil)
			expected := Code("ui_failed")
			if mode == "stdout-overflow" {
				expected = "ui_response_limit"
			}
			if data != nil || err != expected {
				t.Fatal("partial output or diagnostic escaped")
			}
			waitIdle(t)
		})
	}
}
func TestUIMalformedStartFailureAndSequentialRelease(t *testing.T) {
	for i := 0; i < 3; i++ {
		data, err := supervise(context.Background(), fixtureCommand(t, "echo"), nil)
		if err != nil || string(data) != `{"Version":1}` {
			t.Fatal("sequential slot not released")
		}
	}
	data, err := supervise(context.Background(), fixtureCommand(t, "malformed"), nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := decodeResponse(data, request{Version: 1, Operation: "folder"}, "windows"); err != Code("ui_response_invalid") {
		t.Fatal("malformed response accepted")
	}
	if _, err := supervise(context.Background(), exec.Command(filepath.Join(t.TempDir(), "missing-helper")), nil); err != Code("ui_unavailable") {
		t.Fatal(err)
	}
	if len(uiSlot) != 0 {
		t.Fatal("start failure leaked slot")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := supervise(ctx, fixtureCommand(t, "echo"), nil); err != Code("ui_cancelled") {
		t.Fatal(err)
	}
}
