package presetconsent

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"sync/atomic"

	"makersvault/slicer-bridge/internal/presetui"
)

// Test-only stdin controls simulate a human completing/cancelling a dialog.
// They are not HTTP routes or native-provider qualification. Never dispatched
// by production main or by a normal test run.
func servePickerFixture() int {
	var calls, picks atomic.Int32
	commands := make(chan byte, 1)
	b := fakeBackend(&calls)
	b.pick = func(ctx context.Context) (string, error) {
		picks.Add(1)
		select {
		case command := <-commands:
			if command == 'n' {
				return "", presetui.Code("ui_cancelled")
			}
			if command == 'f' {
				return "", presetui.Code("ui_unavailable")
			}
			return filepath.Join(syntheticRoot(), "PRIVATE_PICKED_FOLDER"), nil
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
	s, err := newSession(context.Background(), config(), b)
	if err != nil {
		return 1
	}
	h, err := StartLocal(context.Background(), s)
	if err != nil {
		s.Close()
		return 1
	}
	defer h.Close()
	encoder := json.NewEncoder(os.Stdout)
	if encoder.Encode(struct{ Kind, URL string }{"ready", h.URL()}) != nil {
		return 1
	}
	consumed := make(chan string, 1)
	go func() {
		digest := ""
		defer func() { h.Close(); consumed <- digest }()
		for {
			var command [1]byte
			if n, _ := os.Stdin.Read(command[:]); n != 1 {
				return
			}
			switch command[0] {
			case 'r', 'n', 'f':
				select {
				case commands <- command[0]:
				case <-s.ctx.Done():
					return
				}
			case 't':
				if data, err := s.TakeApproved(); err == nil {
					sum := sha256.Sum256(data)
					digest = hex.EncodeToString(sum[:])
				}
				return
			default:
				return
			}
		}
	}()
	<-h.Done()
	_ = os.Stdin.Close()
	digest := <-consumed
	// Join the cooperative synthetic callback, without changing production host
	// teardown semantics or claiming native provider cleanup.
	s.mu.Lock()
	op := s.picker
	s.mu.Unlock()
	if op != nil {
		<-op.done
	}
	if encoder.Encode(struct {
		Kind, Stage, Digest string
		Calls, PickerCalls  int32
	}{"closed", s.View().Stage, digest, calls.Load(), picks.Load()}) != nil {
		return 1
	}
	return 0
}
