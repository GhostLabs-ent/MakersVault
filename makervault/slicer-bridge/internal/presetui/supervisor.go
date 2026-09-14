package presetui

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"runtime"
	"sync"
)

// One active or unreaped UI helper per parent process. Never repeatedly spawn work
// behind a stalled kernel wait. This is not a cross-process installation lock.
var uiSlot = make(chan struct{}, 1)

func contextCode(ctx context.Context) Code {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return "ui_timeout"
	}
	return "ui_cancelled"
}

// OpenBrowser sends only the exact local preview URL to a single-use UI child.
func OpenBrowser(ctx context.Context, target string) error {
	_, err := run(ctx, request{Version: 1, Operation: "browser", URL: target})
	return err
}

// Folder has no exported/JSON path field. Path is for a local consent owner only,
// never a server-supplied root or a grant to read the selected filesystem.
type Folder struct{ path string }

func (f Folder) Path() string { return f.path }

func PickFolder(ctx context.Context) (Folder, error) {
	value, err := run(ctx, request{Version: 1, Operation: "folder"})
	return Folder{value}, err
}

func uiEnvironment(platform string, lookup func(string) string) []string {
	values := []string{"GORACE=atexit_sleep_ms=0"}
	if platform == "windows" {
		// Desktop/profile paths only; no PATH, COMSPEC, BROWSER or arbitrary credentials.
		// This is separate from the unchanged, more restricted file-worker environment.
		for _, key := range []string{"SystemRoot", "SystemDrive", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"} {
			if value := lookup(key); value != "" {
				values = append(values, key+"="+value)
			}
		}
	}
	return values
}

func run(ctx context.Context, req request) (string, error) {
	if ctx == nil {
		return "", Code("ui_unavailable")
	}
	timeout := BrowserTimeout
	if req.Operation == "folder" {
		timeout = PickerTimeout
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	if ctx.Err() != nil {
		return "", contextCode(ctx)
	}
	if !validRequest(req) {
		return "", Code("ui_request_invalid")
	}
	if runtime.GOOS != "windows" || (runtime.GOARCH != "amd64" && runtime.GOARCH != "arm64") {
		return "", Code("ui_platform_unsupported")
	}
	data, err := json.Marshal(req)
	if err != nil || len(data) > MaxRequestBytes {
		return "", Code("ui_request_invalid")
	}
	executable, err := os.Executable()
	if err != nil {
		return "", Code("ui_unavailable")
	}
	cmd := exec.Command(executable, Argument)
	cmd.Env = uiEnvironment(runtime.GOOS, os.Getenv)
	result, err := supervise(ctx, cmd, data)
	if err != nil {
		return "", err
	}
	value, err := decodeResponse(result, req, runtime.GOOS)
	if ctx.Err() != nil {
		return "", contextCode(ctx)
	}
	return value, err
}

type event struct {
	kind string
	data []byte
	err  error
}

func supervise(ctx context.Context, cmd *exec.Cmd, request []byte) ([]byte, error) {
	if ctx.Err() != nil {
		return nil, contextCode(ctx)
	}
	select {
	case uiSlot <- struct{}{}:
	default:
		return nil, Code("ui_busy")
	}
	started := false
	defer func() {
		if !started {
			<-uiSlot
		}
	}()
	var pipes []*os.File
	defer func() {
		for _, pipe := range pipes {
			pipe.Close()
		}
	}()
	newPipe := func() (*os.File, *os.File, error) {
		r, w, err := os.Pipe()
		if err == nil {
			pipes = append(pipes, r, w)
		}
		return r, w, err
	}
	inR, inW, err := newPipe()
	if err != nil {
		return nil, Code("ui_unavailable")
	}
	outR, outW, err := newPipe()
	if err != nil {
		return nil, Code("ui_unavailable")
	}
	errR, errW, err := newPipe()
	if err != nil {
		return nil, Code("ui_unavailable")
	}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = inR, outW, errW
	if ctx.Err() != nil {
		return nil, contextCode(ctx)
	}
	if err := cmd.Start(); err != nil {
		return nil, Code("ui_unavailable")
	}
	started = true
	var releaseOnce sync.Once
	release := func() { releaseOnce.Do(func() { <-uiSlot }) }
	inR.Close()
	outW.Close()
	errW.Close()
	// No Cmd-managed pipe-copy goroutines/WaitDelay: we own and close the pipes.
	// The parent never waits synchronously for a killed child stuck in kernel I/O.
	finished := make(chan struct{})
	defer close(finished)
	events := make(chan event, 4)
	var copying sync.WaitGroup
	copying.Add(3)
	go func() {
		defer copying.Done()
		_, err := inW.Write(request)
		inW.Close()
		events <- event{kind: "stdin", err: err}
	}()
	go func() {
		defer copying.Done()
		data, err := io.ReadAll(io.LimitReader(outR, MaxResponseBytes+1))
		if len(data) > MaxResponseBytes {
			err = Code("ui_response_limit")
			data = nil
		}
		events <- event{kind: "stdout", data: data, err: err}
	}()
	go func() {
		defer copying.Done()
		count, err := io.Copy(io.Discard, io.LimitReader(errR, MaxStderrBytes+1))
		if count > 0 {
			err = Code("ui_failed")
		} // diagnostics never reach caller/logs
		events <- event{kind: "stderr", err: err}
	}()
	go func() {
		err := cmd.Wait()
		events <- event{kind: "exit", err: err}
		<-finished
		copying.Wait()
		release() // release only after actual reap and pipe cleanup
	}()
	var response []byte
	for remaining := 4; remaining > 0; remaining-- {
		select {
		case <-ctx.Done():
			_ = cmd.Process.Kill()
			return nil, contextCode(ctx)
		case item := <-events:
			if item.err != nil {
				_ = cmd.Process.Kill()
				if ctx.Err() != nil {
					return nil, contextCode(ctx)
				}
				if item.err == Code("ui_response_limit") {
					return nil, item.err
				}
				return nil, Code("ui_failed")
			}
			if item.kind == "stdout" {
				response = item.data
			}
		}
	}
	if ctx.Err() != nil {
		return nil, contextCode(ctx)
	}
	// All four completion events include actual process reap and finished I/O;
	// successful sequential operations need not race the reaper for the slot.
	copying.Wait()
	release()
	return response, nil
}
