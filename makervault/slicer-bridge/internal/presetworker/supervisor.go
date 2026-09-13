package presetworker

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"runtime"
	"sync"

	"makersvault/slicer-bridge/internal/printerpreset"
)

// One active or unreaped worker per parent process. Never repeatedly spawn work
// behind a stalled kernel wait. This is not a cross-process installation lock.
var workerSlot = make(chan struct{}, 1)

func contextCode(ctx context.Context) Code {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return "worker_timeout"
	}
	return "worker_cancelled"
}

// Run reexecutes only this executable with a constant argument. No shell, PATH
// lookup, external helper, browser URL, source path in argv or inherited secrets.
// Requires a future matching main dispatch; not activated in the bridge today.
func Run(ctx context.Context, request Request) (Response, error) {
	ctx, cancel := context.WithTimeout(ctx, printerpreset.MaxDuration)
	defer cancel()
	if ctx.Err() != nil {
		return Response{}, contextCode(ctx)
	}
	data, wire, err := marshalRequest(request)
	if err != nil {
		return Response{}, err
	}
	executable, err := os.Executable()
	if err != nil {
		return Response{}, Code("worker_unavailable")
	}
	cmd := exec.Command(executable, Argument)
	cmd.Env = []string{"GORACE=atexit_sleep_ms=0"}
	if runtime.GOOS == "windows" {
		cmd.Env = append(cmd.Env, "SystemRoot="+os.Getenv("SystemRoot"))
	}
	response, err := supervise(ctx, cmd, data)
	if err != nil {
		return Response{}, err
	}
	result, err := decodeResponse(response, wire)
	if ctx.Err() != nil {
		return Response{}, contextCode(ctx)
	}
	return result, err
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
	case workerSlot <- struct{}{}:
	default:
		return nil, Code("worker_busy")
	}
	started := false
	defer func() {
		if !started {
			<-workerSlot
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
		return nil, Code("worker_unavailable")
	}
	outR, outW, err := newPipe()
	if err != nil {
		return nil, Code("worker_unavailable")
	}
	errR, errW, err := newPipe()
	if err != nil {
		return nil, Code("worker_unavailable")
	}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = inR, outW, errW
	if ctx.Err() != nil {
		return nil, contextCode(ctx)
	}
	if err := cmd.Start(); err != nil {
		return nil, Code("worker_unavailable")
	}
	started = true
	var releaseOnce sync.Once
	release := func() { releaseOnce.Do(func() { <-workerSlot }) }
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
			err = Code("worker_response_limit")
			data = nil
		}
		events <- event{kind: "stdout", data: data, err: err}
	}()
	go func() {
		defer copying.Done()
		count, err := io.Copy(io.Discard, io.LimitReader(errR, MaxStderrBytes+1))
		if count > 0 {
			err = Code("worker_failed")
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
				if item.err == Code("worker_response_limit") {
					return nil, item.err
				}
				return nil, Code("worker_failed")
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
