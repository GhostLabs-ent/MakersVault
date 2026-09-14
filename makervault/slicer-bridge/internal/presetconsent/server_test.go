package presetconsent

import (
	"bufio"
	"context"
	"fmt"
	"html"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/presetfiles"
)

func testHost(t *testing.T, s *Session, limits serverLimits) *LocalServer {
	t.Helper()
	h, err := startLocal(context.Background(), s, limits)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(h.Close)
	return h
}
func localClient(t *testing.T) *http.Client {
	t.Helper()
	transport := &http.Transport{Proxy: nil}
	t.Cleanup(transport.CloseIdleConnections)
	return &http.Client{Transport: transport, Timeout: 3 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}
func fetchPage(t *testing.T, client *http.Client, target string, form url.Values) (int, string, http.Header) {
	t.Helper()
	method, body := "GET", ""
	if form != nil {
		method, body = "POST", form.Encode()
	}
	req, err := http.NewRequest(method, target, strings.NewReader(body))
	if err != nil {
		t.Fatal("request construction failed")
	}
	if form != nil {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("Origin", "http://"+req.URL.Host)
	}
	response, err := client.Do(req)
	if err != nil {
		t.Fatal("loopback HTTP request failed")
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, MaxPageBytes+1))
	if err != nil || len(data) > MaxPageBytes {
		t.Fatal("invalid HTTP response")
	}
	return response.StatusCode, string(data), response.Header
}
func formFor(t *testing.T, body, decision string) url.Values {
	t.Helper()
	form := url.Values{"decision": {decision}}
	for _, name := range []string{"csrf", "revision"} {
		match := regexp.MustCompile(`name="` + name + `" value="([^"]+)"`).FindStringSubmatch(body)
		if len(match) != 2 {
			t.Fatal("missing form field")
		}
		form.Set(name, html.UnescapeString(match[1]))
	}
	return form
}
func waitDone(t *testing.T, h *LocalServer) {
	t.Helper()
	select {
	case <-h.Done():
	case <-time.After(3 * time.Second):
		t.Fatal("host teardown exceeded budget")
	}
	u, _ := url.Parse(h.URL())
	conn, err := net.DialTimeout("tcp4", u.Host, 100*time.Millisecond)
	if err == nil {
		conn.Close()
		t.Fatal("listener still available after teardown")
	}
}
func waitSlots(t *testing.T, h *LocalServer, n int) {
	t.Helper()
	deadline := time.NewTimer(time.Second)
	defer deadline.Stop()
	tick := time.NewTicker(time.Millisecond)
	defer tick.Stop()
	for len(h.listener.slots) != n {
		select {
		case <-tick.C:
		case <-deadline.C:
			t.Fatal("connection budget did not converge")
		}
	}
}

func TestLocalServerHTTPSelectionAndConsumption(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	h := testHost(t, s, localLimits())
	client := localClient(t)
	code, body, headers := fetchPage(t, client, h.URL(), nil)
	if code != 200 || calls.Load() != 0 || headers.Get("Cache-Control") != "no-store" || headers.Get("Referrer-Policy") != "same-origin" || !strings.Contains(headers.Get("Content-Security-Policy"), "frame-ancestors 'none'") {
		t.Fatal("initial HTTP boundary")
	}
	for _, step := range []struct{ decision, stage string }{{"allow", "roots"}, {"choose", "accounts"}, {"choose", "presets"}, {"preview", "review"}, {"approve", "approved"}} {
		form := formFor(t, body, step.decision)
		v := s.View()
		if step.decision == "choose" || step.decision == "preview" {
			form.Set("choice", v.Choices[0].ID)
		}
		if step.decision == "approve" {
			form.Set("digest", v.Digest)
		}
		code, body, _ = fetchPage(t, client, h.URL(), form)
		if code != 200 || s.View().Stage != step.stage {
			t.Fatal("explicit HTTP transition failed")
		}
	}
	if calls.Load() != 4 {
		t.Fatal("HTTP performed extra scans")
	}
	review := s.View().Preview
	data, err := s.TakeApproved()
	if err != nil || string(data) != review {
		t.Fatal("HTTP approved bytes changed")
	}
	waitDone(t, h)
	if s.View().Stage != "consumed" {
		t.Fatal("consumption state lost during teardown")
	}
}

func TestLocalServerHTTPNegativeControls(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	h := testHost(t, s, localLimits())
	client := localClient(t)
	_, body, _ := fetchPage(t, client, h.URL(), nil)
	for _, name := range []string{"wrong-host", "foreign-origin", "missing-origin", "cross-site", "missing-csrf", "unknown-field", "duplicate-csrf", "raw-root", "wrong-nonce", "query", "oversized-body", "method"} {
		t.Run(name, func(t *testing.T) {
			form := formFor(t, body, "allow")
			target := h.URL()
			method := "POST"
			expected := 403
			switch name {
			case "missing-csrf":
				form.Del("csrf")
			case "unknown-field":
				form.Set("unexpected", "x")
				expected = 400
			case "duplicate-csrf":
				form.Add("csrf", form.Get("csrf"))
				expected = 400
			case "raw-root":
				form.Set("root", syntheticRoot())
				expected = 400
			case "wrong-nonce":
				target += "x"
			case "query":
				target += "?x=1"
			case "oversized-body":
				form.Set("revision", strings.Repeat("x", MaxFormBytes+1))
				expected = 400
			case "method":
				method = "PUT"
				expected = 405
			}
			req, _ := http.NewRequest(method, target, strings.NewReader(form.Encode()))
			req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
			req.Header.Set("Origin", "http://"+req.URL.Host)
			switch name {
			case "wrong-host":
				req.Host = "attacker.example"
			case "foreign-origin":
				req.Header.Set("Origin", "https://attacker.example")
			case "missing-origin":
				req.Header.Del("Origin")
			case "cross-site":
				req.Header.Set("Sec-Fetch-Site", "cross-site")
			}
			res, err := client.Do(req)
			if err != nil {
				t.Fatal("negative control request failed")
			}
			defer res.Body.Close()
			_, _ = io.Copy(io.Discard, res.Body)
			if res.StatusCode != expected || s.View().Stage != "consent" || calls.Load() != 0 {
				t.Fatal("negative HTTP control changed consent")
			}
		})
	}
}

func TestLocalServerConnectionBudgetAndRelease(t *testing.T) {
	var calls atomic.Int32
	limits := localLimits()
	limits.connections = 2
	limits.shutdown = 50 * time.Millisecond
	h := testHost(t, fixtureSession(t, fakeBackend(&calls)), limits)
	u, _ := url.Parse(h.URL())
	dial := func() net.Conn {
		c, e := net.DialTimeout("tcp4", u.Host, time.Second)
		if e != nil {
			t.Fatal("dial failed")
		}
		t.Cleanup(func() { c.Close() })
		return c
	}
	a, b := dial(), dial()
	waitSlots(t, h, 2)
	extra := dial()
	_ = extra.SetReadDeadline(time.Now().Add(time.Second))
	var one [1]byte
	if _, err := extra.Read(one[:]); err == nil {
		t.Fatal("over-budget connection admitted")
	} else if ne, ok := err.(net.Error); ok && ne.Timeout() {
		t.Fatal("over-budget socket not closed")
	}
	_ = a.Close()
	waitSlots(t, h, 1)
	_ = b.Close()
	waitSlots(t, h, 0)
	if code, _, _ := fetchPage(t, localClient(t), h.URL(), nil); code != 200 {
		t.Fatal("released slot unavailable")
	}
	h.Close()
	waitDone(t, h)
	waitSlots(t, h, 0)
}

func TestLocalServerReadHeaderBodyAndIdleDeadlines(t *testing.T) {
	for _, kind := range []string{"header", "body", "idle", "large-header"} {
		t.Run(kind, func(t *testing.T) {
			var calls atomic.Int32
			limits := localLimits()
			limits.header = 150 * time.Millisecond
			limits.read = 250 * time.Millisecond
			limits.idle = 150 * time.Millisecond
			limits.shutdown = 50 * time.Millisecond
			h := testHost(t, fixtureSession(t, fakeBackend(&calls)), limits)
			u, _ := url.Parse(h.URL())
			c, err := net.DialTimeout("tcp4", u.Host, time.Second)
			if err != nil {
				t.Fatal("dial failed")
			}
			defer c.Close()
			_ = c.SetDeadline(time.Now().Add(2 * time.Second))
			reader := bufio.NewReader(c)
			switch kind {
			case "header":
				_, _ = fmt.Fprint(c, "GET "+u.Path+" HTTP/1.1\r\nHost: ")
			case "body":
				_, _ = fmt.Fprintf(c, "POST %s HTTP/1.1\r\nHost: %s\r\nOrigin: http://%s\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: 100\r\n\r\ncsrf=", u.Path, u.Host, u.Host)
			case "idle":
				_, _ = fmt.Fprintf(c, "GET %s HTTP/1.1\r\nHost: %s\r\n\r\n", u.Path, u.Host)
				r, e := http.ReadResponse(reader, nil)
				if e != nil || r.StatusCode != 200 {
					t.Fatal("initial keepalive failed")
				}
				_, _ = io.Copy(io.Discard, r.Body)
				r.Body.Close()
			case "large-header":
				_, _ = fmt.Fprintf(c, "GET %s HTTP/1.1\r\nHost: %s\r\nX-Large: %s\r\n\r\n", u.Path, u.Host, strings.Repeat("x", 32<<10))
			}
			data, err := io.ReadAll(reader)
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				t.Fatal("server did not close bounded read/idle request")
			}
			if kind == "body" && !strings.Contains(string(data), "400 Bad Request") {
				t.Fatal("slow body was not refused")
			}
			if kind == "large-header" && !strings.Contains(string(data), "431 Request Header Fields Too Large") {
				t.Fatal("oversized headers were not refused")
			}
			if calls.Load() != 0 {
				t.Fatal("invalid/idle request read source")
			}
		})
	}
}

func TestLocalServerRevocationExpiryAndAcceptFailure(t *testing.T) {
	for _, kind := range []string{"owner", "session", "expiry", "listener", "launch-failure"} {
		t.Run(kind, func(t *testing.T) {
			var calls atomic.Int32
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			cfg := config()
			if kind == "expiry" {
				cfg.ExpiresAt = time.Now().Add(150 * time.Millisecond)
			}
			s, err := newSession(ctx, cfg, fakeBackend(&calls))
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			h, err := StartLocal(ctx, s)
			if err != nil {
				t.Fatal(err)
			}
			defer h.Close()
			switch kind {
			case "owner":
				cancel()
			case "session":
				s.Close()
			case "listener":
				_ = h.listener.Close()
			case "launch-failure":
				h.Close() /* simulated owner response; no native launcher executed */
			}
			waitDone(t, h)
			if data, e := s.TakeApproved(); data != nil || e == nil || calls.Load() != 0 {
				t.Fatal("closed host kept authority or scanned")
			}
		})
	}
}

func TestLocalServerSingleOwnerAndConcurrentClose(t *testing.T) {
	var calls atomic.Int32
	s := fixtureSession(t, fakeBackend(&calls))
	h := testHost(t, s, localLimits())
	if other, err := StartLocal(context.Background(), s); other != nil || err == nil {
		t.Fatal("second listener for same session")
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); h.Close() }()
	}
	wg.Wait()
	waitDone(t, h)
	if other, err := StartLocal(context.Background(), s); other != nil || err == nil {
		t.Fatal("closed session rehosted")
	}
	if other, err := StartLocal(context.Background(), nil); other != nil || err == nil {
		t.Fatal("nil session hosted")
	}
}

func TestLocalServerRequestDeadlineCancelsBackend(t *testing.T) {
	var calls atomic.Int32
	runner := fakeBackend(&calls)
	cancelled := make(chan struct{})
	runner.hints = func(ctx context.Context) ([]presetfiles.BambuLocation, error) {
		<-ctx.Done()
		close(cancelled)
		return nil, ctx.Err()
	}
	s := fixtureSession(t, runner)
	limits := localLimits()
	limits.request = 100 * time.Millisecond
	h := testHost(t, s, limits)
	client := localClient(t)
	_, body, _ := fetchPage(t, client, h.URL(), nil)
	code, _, _ := fetchPage(t, client, h.URL(), formFor(t, body, "allow"))
	select {
	case <-cancelled:
	default:
		t.Fatal("backend did not observe deadline")
	}
	if code != 409 || s.View().Stage != "failed" {
		t.Fatal("timed-out work produced consent")
	}
}

func TestLocalServerCancelInflightHTTP(t *testing.T) {
	var calls atomic.Int32
	runner := fakeBackend(&calls)
	started, cancelled := make(chan struct{}), make(chan struct{})
	runner.hints = func(ctx context.Context) ([]presetfiles.BambuLocation, error) {
		close(started)
		<-ctx.Done()
		close(cancelled)
		return nil, ctx.Err()
	}
	s := fixtureSession(t, runner)
	h := testHost(t, s, localLimits())
	client := localClient(t)
	_, body, _ := fetchPage(t, client, h.URL(), nil)
	form := formFor(t, body, "allow")
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		req, _ := http.NewRequest("POST", h.URL(), strings.NewReader(form.Encode()))
		u, _ := url.Parse(h.URL())
		req.Header.Set("Origin", "http://"+u.Host)
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		r, e := client.Do(req)
		if e == nil {
			_, _ = io.Copy(io.Discard, r.Body)
			r.Body.Close()
		}
	}()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("work did not start")
	}
	// A separate connection submits the old page's still-valid Cancel action.
	code, _, _ := fetchPage(t, client, h.URL(), formFor(t, body, "cancel"))
	if code != 200 {
		t.Fatal("cancel form failed")
	}
	waitDone(t, h)
	select {
	case <-cancelled:
	case <-time.After(time.Second):
		t.Fatal("work not cancelled")
	}
	select {
	case <-finished:
	case <-time.After(time.Second):
		t.Fatal("request remained blocked")
	}
	if s.View().Preview != "" || s.View().Stage != "cancelled" {
		t.Fatal("late HTTP work resurrected state")
	}
}

func TestLocalServerDefaultLimitsAndWorkBudget(t *testing.T) {
	var calls atomic.Int32
	runner := fakeBackend(&calls)
	started, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
	defer close(release)
	runner.hints = func(context.Context) ([]presetfiles.BambuLocation, error) {
		close(started)
		<-release
		return nil, Code("fixture_stopped")
	}
	s := fixtureSession(t, runner)
	limits := localLimits()
	if limits.connections != 8 || limits.headers != 8<<10 || limits.header != 3*time.Second ||
		limits.read != 5*time.Second || limits.write != 20*time.Second || limits.idle != 5*time.Second ||
		limits.request != 20*time.Second || limits.shutdown != 2*time.Second {
		t.Fatal("default resource budgets changed")
	}
	limits.connections = 1
	h := testHost(t, s, limits)
	if !h.server.Protocols.HTTP1() || h.server.Protocols.UnencryptedHTTP2() || h.server.Protocols.HTTP2() {
		t.Fatal("unexpected HTTP multiplexing")
	}
	client := localClient(t)
	_, body, _ := fetchPage(t, client, h.URL(), nil)
	form := formFor(t, body, "allow")
	u, _ := url.Parse(h.URL())
	// Hold one handler independent of any TCP slot, as can happen during teardown.
	req := httptest.NewRequest("POST", h.URL(), strings.NewReader(form.Encode()))
	req.RemoteAddr = "127.0.0.1:12345"
	req.Header.Set("Origin", "http://"+u.Host)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	go func() { defer close(finished); h.server.Handler.ServeHTTP(httptest.NewRecorder(), req) }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("handler did not start")
	}
	code, _, headers := fetchPage(t, client, h.URL(), nil)
	if code != 503 || headers.Get("Cache-Control") != "no-store" {
		t.Fatal("work budget bypassed via separate connection")
	}
	// The injected non-cooperative callback is deliberately not a production worker.
	h.Close()
	waitDone(t, h)
	t.Cleanup(func() {
		select {
		case <-finished:
		case <-time.After(time.Second):
			t.Error("fixture handler did not return")
		}
	})
}
