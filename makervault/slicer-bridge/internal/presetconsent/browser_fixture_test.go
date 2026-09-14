package presetconsent

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"sync/atomic"
	"time"
)

// Test binary only. The private readiness pipe is never a public endpoint/log.
// No production dispatch, actual profile, browser command or server API exists.
func serveBrowserFixture() int {
	var calls atomic.Int32
	cfg := config()
	cfg.ExpiresAt = time.Now().Add(60 * time.Second)
	s, err := newSession(context.Background(), cfg, fakeBackend(&calls))
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
		var command [1]byte
		n, _ := os.Stdin.Read(command[:])
		digest := ""
		if n == 1 && command[0] == 't' {
			if data, err := s.TakeApproved(); err == nil {
				sum := sha256.Sum256(data)
				digest = hex.EncodeToString(sum[:])
			}
		}
		h.Close()
		consumed <- digest
	}()
	<-h.Done()
	// Closing stdin on expiry/HTTP cancel releases the owned pipe reader too.
	_ = os.Stdin.Close()
	digest := <-consumed
	if encoder.Encode(struct {
		Kind, Stage, Digest string
		Calls               int32
	}{"closed", s.View().Stage, digest, calls.Load()}) != nil {
		return 1
	}
	return 0
}
