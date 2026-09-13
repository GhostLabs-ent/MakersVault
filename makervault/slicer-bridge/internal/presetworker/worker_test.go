package presetworker

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/presetfiles"
	"makersvault/slicer-bridge/internal/printerpreset"
)

// Only this test executable dispatches the worker today; bridge main is unchanged.
func TestMain(m *testing.M) {
	if len(os.Args) == 2 && os.Args[1] == Argument {
		if os.Getenv("MAKERSVAULT_PARENT_SECRET") != "" {
			os.Exit(19)
		}
		os.Exit(Serve(os.Stdin, os.Stdout))
	}
	if len(os.Args) == 2 && strings.HasPrefix(os.Args[1], "--fixture-") {
		mode := strings.TrimPrefix(os.Args[1], "--fixture-")
		if mode == "blocked-stdin" || mode == "hang" {
			for {
				time.Sleep(time.Hour)
			}
		}
		io.Copy(io.Discard, os.Stdin)
		switch mode {
		case "stdout-overflow":
			os.Stdout.Write(bytes.Repeat([]byte("x"), MaxResponseBytes+1))
			for {
				time.Sleep(time.Hour)
			}
		case "stderr-overflow":
			os.Stderr.Write(bytes.Repeat([]byte("x"), MaxStderrBytes+1))
			for {
				time.Sleep(time.Hour)
			}
		case "stderr-secret":
			os.Stderr.WriteString("SYNTHETIC_SECRET /private/path token=value")
			os.Exit(0)
		case "malformed":
			os.Stdout.WriteString(`{"Version":1`)
			os.Exit(0)
		case "failed":
			os.Stdout.WriteString(`{"Version":1,"Response":{"names":["a.json"]}}`)
			os.Exit(7)
		case "echo":
			os.Stdout.WriteString(`{"Version":1,"Response":{"names":["a.json"]}}`)
			os.Exit(0)
		}
		os.Exit(17)
	}
	os.Exit(m.Run())
}

func requestFixture(t *testing.T) Request {
	t.Helper()
	root := t.TempDir()
	for _, name := range []string{"base.json", "common.json", "child.json"} {
		data, err := os.ReadFile(filepath.Join("../printerpreset/testdata", name))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, name), data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	return Request{Operation: "project", Inputs: []presetfiles.Input{{Root: root,
		Files:  []string{"child.json", "base.json", "common.json"},
		Source: printerpreset.Source{Namespace: "private-local-selection", Kind: printerpreset.System}}},
		Picks: []Pick{{Kind: printerpreset.System, Name: "Fixture P1S 0.4"}}}
}

func fixtureCommand(t *testing.T, mode string) *exec.Cmd {
	t.Helper()
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(self, "--fixture-"+mode)
	cmd.Env = []string{"GORACE=atexit_sleep_ms=0"}
	if root := os.Getenv("SystemRoot"); root != "" {
		cmd.Env = append(cmd.Env, "SystemRoot="+root)
	}
	return cmd
}

func waitIdle(t *testing.T) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for len(workerSlot) != 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if len(workerSlot) != 0 {
		t.Fatal("ordinary test worker was not reaped; slot remains held")
	}
}

func TestWorkerListAndProjectRoundTrip(t *testing.T) {
	request := requestFixture(t)
	t.Setenv("MAKERSVAULT_PARENT_SECRET", "SYNTHETIC_SECRET")
	response, err := Run(context.Background(), Request{Operation: "list", Root: request.Inputs[0].Root})
	if err != nil || strings.Join(response.Names, ",") != "base.json,child.json,common.json" {
		t.Fatalf("%v %v", response, err)
	}
	response, err = Run(context.Background(), request)
	if err != nil || len(response.Candidates) != 1 || !response.Candidates[0].Complete() {
		t.Fatalf("%v %v", response, err)
	}
	data, err := json.Marshal(response)
	if err != nil {
		t.Fatal(err)
	}
	for _, secret := range []string{request.Inputs[0].Root, "private-local-selection", "FAKE_PRIVATE", "SYNTHETIC_SECRET", "private.invalid"} {
		if bytes.Contains(data, []byte(secret)) {
			t.Fatal("private source/environment crossed response")
		}
	}
}

func TestWorkerProjectionIsAtomic(t *testing.T) {
	request := requestFixture(t)
	request.Picks = append(request.Picks, Pick{Kind: printerpreset.System, Name: "Missing fixture"})
	response, err := Run(context.Background(), request)
	if err != Code("preset_not_found") || len(response.Candidates) != 0 {
		t.Fatalf("partial result: %v %v", response, err)
	}
}

func TestWorkerStopsHungProcessAndBlockedInput(t *testing.T) {
	for _, mode := range []string{"hang", "blocked-stdin"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
			defer cancel()
			start := time.Now()
			data, err := supervise(ctx, fixtureCommand(t, mode), bytes.Repeat([]byte("x"), MaxRequestBytes))
			if data != nil || err != Code("worker_timeout") {
				t.Fatalf("%q %v", data, err)
			}
			if time.Since(start) > 2*time.Second {
				t.Fatal("parent waited for stalled work")
			}
			waitIdle(t)
		})
	}
}

func TestWorkerCancellationAndBusySlot(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() { _, err := supervise(ctx, fixtureCommand(t, "hang"), nil); result <- err }()
	deadline := time.Now().Add(2 * time.Second)
	for len(workerSlot) == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if len(workerSlot) == 0 {
		t.Fatal("worker never started")
	}
	if data, err := supervise(context.Background(), fixtureCommand(t, "echo"), nil); data != nil || err != Code("worker_busy") {
		t.Fatalf("%q %v", data, err)
	}
	cancel()
	select {
	case err := <-result:
		if err != Code("worker_cancelled") {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("cancel did not return")
	}
	waitIdle(t)
}

func TestWorkerOutputBudgetAndDiagnosticRedaction(t *testing.T) {
	for _, mode := range []string{"stdout-overflow", "stderr-overflow", "stderr-secret", "failed"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			data, err := supervise(ctx, fixtureCommand(t, mode), nil)
			expected := Code("worker_failed")
			if mode == "stdout-overflow" {
				expected = "worker_response_limit"
			}
			if data != nil || err != expected {
				t.Fatalf("%q %v", data, err)
			}
			waitIdle(t)
		})
	}
}

func TestWorkerMalformedOutputAndStartFailure(t *testing.T) {
	data, err := supervise(context.Background(), fixtureCommand(t, "malformed"), nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: "list"}); err != Code("worker_response_invalid") {
		t.Fatal(err)
	}
	cmd := exec.Command(filepath.Join(t.TempDir(), "missing-worker"))
	if data, err := supervise(context.Background(), cmd, nil); data != nil || err != Code("worker_unavailable") {
		t.Fatalf("%q %v", data, err)
	}
	if len(workerSlot) != 0 {
		t.Fatal("start failure leaked worker slot")
	}
}

func TestWorkerCancelledBeforeStart(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := Run(ctx, Request{}); err != Code("worker_cancelled") {
		t.Fatal(err)
	}
	ctx, cancel = context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	if _, err := Run(ctx, Request{}); err != Code("worker_timeout") {
		t.Fatal(err)
	}
	if len(workerSlot) != 0 {
		t.Fatal("pre-cancelled request acquired slot")
	}
}

func TestWorkerRejectsAmbiguousOrUnboundedFrames(t *testing.T) {
	frames := []string{`{"Version":1,"Version":1}`, `{"Version":1,"version":1}`, `{"Version":1,"Unknown":true}`,
		`{"Version":1,"Verſion":1}`,
		`{"Version":1} {}`, `{"Version":2,"Operation":"list","Root":"/private"}`, `null`,
		`{"Version":1,"Operation":"list","Root":"/private","Inputs":[{}]}`,
		strings.Repeat("[", 20) + "0" + strings.Repeat("]", 20), "{\"Root\":\"\xff\"}"}
	for _, frame := range frames {
		var output bytes.Buffer
		if Serve(strings.NewReader(frame), &output) != 0 {
			t.Fatal("error envelope failed")
		}
		var value envelope
		if err := json.Unmarshal(output.Bytes(), &value); err != nil {
			t.Fatal(err)
		}
		if value.Code != "worker_request_invalid" || len(value.Response.Names) != 0 || len(value.Response.Candidates) != 0 {
			t.Fatalf("ambiguous frame accepted: %s", output.Bytes())
		}
	}
	var output bytes.Buffer
	Serve(strings.NewReader(strings.Repeat("x", MaxRequestBytes+1)), &output)
	if !bytes.Contains(output.Bytes(), []byte("worker_request_limit")) {
		t.Fatal("request size ignored")
	}
}

func TestWorkerResponseIdentityAndErrorCodes(t *testing.T) {
	request := wireRequest{Version: 1, Operation: "list"}
	for _, data := range []string{`{"Version":1,"Code":"SYNTHETIC_SECRET"}`, `{"Version":1,"Code":"source_unsafe","Response":{"names":["a.json"]}}`,
		`{"Version":1,"Response":{"names":["../private.json"]}}`, `{"Version":1,"Response":{"names":["b.json","a.json"]}}`,
		`{"Version":1,"Response":{"unknown":"private"}}`} {
		if _, err := decodeResponse([]byte(data), request); err != Code("worker_response_invalid") {
			t.Fatal(err)
		}
	}
	request.Operation = "project"
	request.Picks = []Pick{{Kind: printerpreset.System, Name: "expected"}}
	if _, err := decodeResponse([]byte(`{"Version":1,"Response":{"candidates":[]}}`), request); err != Code("worker_response_invalid") {
		t.Fatal(err)
	}
	if safeCode(io.EOF) != "worker_source_rejected" || safeCode(printerpreset.Code("private_value")) != "worker_source_rejected" {
		t.Fatal("unknown diagnostics escaped")
	}
}

func TestWorkerRequestAuthorityAndSelectionLimits(t *testing.T) {
	request := requestFixture(t)
	data, err := json.Marshal(request)
	if err != nil || string(data) != "{}" {
		t.Fatal("filesystem authority serialized through public request")
	}
	request.Picks = append(request.Picks, request.Picks[0])
	if _, _, err := marshalRequest(request); err != Code("worker_request_invalid") {
		t.Fatal(err)
	}
	request.Picks = make([]Pick, MaxSelected+1)
	if _, _, err := marshalRequest(request); err != Code("worker_request_limit") {
		t.Fatal(err)
	}
	for _, request := range []Request{{}, {Operation: "shell", Root: "/private"}, {Operation: "list", Root: "/private", Inputs: []presetfiles.Input{{}}}} {
		if _, _, err := marshalRequest(request); err != Code("worker_request_invalid") {
			t.Fatal(err)
		}
	}
}

func FuzzWorkerFrame(f *testing.F) {
	for _, seed := range []string{`{"Version":1}`, `{"Version":1,"version":2}`, `null`, `[]`, `{"Code":"private"}`} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, text string) {
		if len(text) > 4096 {
			return
		}
		var value wireRequest
		_ = decode([]byte(text), &value) // framing only: never filesystem/Serve
	})
}
