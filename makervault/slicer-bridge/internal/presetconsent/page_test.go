package presetconsent

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

func pageRequest(h *LocalHandler, method string, form url.Values) *http.Request {
	r := httptest.NewRequest(method, h.URL(), strings.NewReader(form.Encode()))
	r.RemoteAddr = "127.0.0.1:12000"
	if method == "POST" {
		r.Header.Set("Origin", "http://"+h.host)
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	return r
}
func pageForm(h *LocalHandler, decision string, ids ...string) url.Values {
	return url.Values{"csrf": {h.csrf}, "revision": {h.session.View().Revision}, "decision": {decision}, "choice": ids}
}
func serve(h *LocalHandler, r *http.Request) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}
func handlerFixture(t *testing.T) (*LocalHandler, *atomic.Int32) {
	t.Helper()
	calls := new(atomic.Int32)
	s := fixtureSession(t, fakeBackend(calls))
	h, err := NewLocalHandler(s, "127.0.0.1:43123")
	if err != nil {
		t.Fatal(err)
	}
	return h, calls
}

func TestLocalPageNoReadOnGetAndNoAutomaticChoice(t *testing.T) {
	h, calls := handlerFixture(t)
	w := serve(h, pageRequest(h, "GET", nil))
	if w.Code != 200 || calls.Load() != 0 || !strings.Contains(w.Body.String(), "Allow local reading") || !strings.Contains(w.Body.String(), "Nothing is sent or saved") {
		t.Fatal("GET did work or concealed consent scope")
	}
	for key, want := range map[string]string{"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff"} {
		if w.Header().Get(key) != want {
			t.Fatal("privacy header missing")
		}
	}
	if !strings.Contains(w.Header().Get("Content-Security-Policy"), "default-src 'none'") {
		t.Fatal("active resource policy")
	}
	w = serve(h, pageRequest(h, "POST", pageForm(h, "allow")))
	if w.Code != 200 || calls.Load() != 1 || strings.Contains(w.Body.String(), "checked") || strings.Contains(w.Body.String(), `value="`+syntheticRoot()+`"`) {
		t.Fatal("automatic or path-valued choice")
	}
	if !strings.Contains(w.Body.String(), `type="radio" required`) {
		t.Fatal("explicit selection required")
	}
}

func TestLocalPageRejectsForeignAndMalformedRequests(t *testing.T) {
	for _, kind := range []string{"host", "remote", "path", "query", "empty-query", "raw-path", "origin", "missing-origin", "null-origin", "duplicate-origin", "fetch-site", "csrf", "duplicate-field", "unknown-field", "json", "oversize", "method", "duplicate-choice"} {
		t.Run(kind, func(t *testing.T) {
			h, calls := handlerFixture(t)
			form := pageForm(h, "allow")
			r := pageRequest(h, "POST", form)
			switch kind {
			case "host":
				r.Host = "attacker.example:43123"
			case "remote":
				r.RemoteAddr = "10.0.0.8:12000"
			case "path":
				r.URL.Path = "/other"
			case "query":
				r.URL.RawQuery = "Root=/private"
			case "empty-query":
				r.URL.ForceQuery = true
			case "raw-path":
				r.URL.RawPath = h.path
			case "origin":
				r.Header.Set("Origin", "https://vault.example")
			case "missing-origin":
				r.Header.Del("Origin")
			case "null-origin":
				r.Header.Set("Origin", "null")
			case "duplicate-origin":
				r.Header.Add("Origin", "http://"+h.host)
			case "fetch-site":
				r.Header.Set("Sec-Fetch-Site", "cross-site")
			case "csrf":
				form.Set("csrf", "wrong")
				r = pageRequest(h, "POST", form)
			case "duplicate-field":
				form.Add("decision", "cancel")
				r = pageRequest(h, "POST", form)
			case "unknown-field":
				form.Set("Root", "/private")
				r = pageRequest(h, "POST", form)
			case "json":
				r.Header.Set("Content-Type", "application/json")
			case "oversize":
				form.Set("csrf", strings.Repeat("x", MaxFormBytes+1))
				r = pageRequest(h, "POST", form)
			case "method":
				r.Method = "PUT"
			case "duplicate-choice":
				form["choice"] = make([]string, 101)
				r = pageRequest(h, "POST", form)
			}
			w := serve(h, r)
			if w.Code < 400 || calls.Load() != 0 || h.session.View().Stage != "consent" {
				t.Fatal("rejected request changed consent")
			}
			if strings.Contains(w.Body.String(), "/private") {
				t.Fatal("raw diagnostic leaked")
			}
		})
	}
}

func TestLocalPageStaleFormAndApprovalDigest(t *testing.T) {
	h, calls := handlerFixture(t)
	form := pageForm(h, "allow")
	if serve(h, pageRequest(h, "POST", form)).Code != 200 {
		t.Fatal("consent failed")
	}
	if serve(h, pageRequest(h, "POST", form)).Code != 409 || calls.Load() != 1 {
		t.Fatal("stale form repeated work")
	}
	for _, decision := range []string{"choose", "choose", "preview"} {
		v := h.session.View()
		if serve(h, pageRequest(h, "POST", pageForm(h, decision, v.Choices[0].ID))).Code != 200 {
			t.Fatal("picker transition failed")
		}
	}
	v := h.session.View()
	form = pageForm(h, "approve")
	if serve(h, pageRequest(h, "POST", form)).Code != 409 {
		t.Fatal("missing digest approved")
	}
	form.Set("digest", v.Digest)
	if serve(h, pageRequest(h, "POST", form)).Code != 200 {
		t.Fatal("exact review approval failed")
	}
	if calls.Load() != 4 {
		t.Fatal("HTTP approval triggered scan or transfer")
	}
	if data, err := h.session.TakeApproved(); err != nil || string(data) != v.Preview {
		t.Fatal("reviewed data changed")
	}
}

func TestLocalPageEscapingAndDisplayBudget(t *testing.T) {
	h, _ := handlerFixture(t)
	h.session.mu.Lock()
	h.session.stage = "review"
	h.session.preview = []byte(`<script>alert("private")</script>`)
	h.session.mu.Unlock()
	w := serve(h, pageRequest(h, "GET", nil))
	if strings.Contains(w.Body.String(), "<script>") || !strings.Contains(w.Body.String(), "&lt;script&gt;") {
		t.Fatal("untrusted preview became active markup")
	}
	h.session.mu.Lock()
	h.session.preview = []byte(strings.Repeat("<", MaxPageBytes))
	h.session.mu.Unlock()
	w = serve(h, pageRequest(h, "GET", nil))
	if w.Code != 413 || strings.Contains(w.Body.String(), "<!doctype") {
		t.Fatal("partial oversized page emitted")
	}
	var buffer boundedPage
	if _, err := buffer.WriteString(strings.Repeat("x", MaxPageBytes+1)); err == nil || buffer.Len() != 0 {
		t.Fatal("StringWriter bypassed display budget")
	}
}

func TestLocalHandlerRequiresExactLoopbackAuthority(t *testing.T) {
	h, _ := handlerFixture(t)
	for _, host := range []string{"localhost:43123", "0.0.0.0:43123", "10.0.0.1:43123", "127.0.0.1:0", "127.0.0.1:70000", "127.0.0.1:043123", "[::1]:43123", "127.0.0.1"} {
		if result, err := NewLocalHandler(h.session, host); result != nil || err == nil {
			t.Fatal("noncanonical or nonlocal binding accepted")
		}
	}
	other, err := NewLocalHandler(h.session, h.host)
	if err != nil {
		t.Fatal(err)
	}
	if other.path == h.path || other.csrf == h.csrf || len(h.csrf) != 64 {
		t.Fatal("local nonces reused")
	}
}

func TestLocalPageRenderedFixtures(t *testing.T) {
	h, _ := handlerFixture(t)
	for _, stage := range []string{"consent", "roots", "accounts", "presets", "review", "approved"} {
		w := serve(h, pageRequest(h, "GET", nil))
		if w.Code != 200 || h.session.View().Stage != stage {
			t.Fatal("fixture state failed")
		}
		// Optional synthetic browser artifacts in the verifier's owned evidence
		// mount. No user configuration, actual listener, or overwrite of old output.
		if info, err := os.Stat("/evidence"); err == nil && info.IsDir() {
			file, err := os.OpenFile(filepath.Join("/evidence", "consent-"+stage+".html"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
			if err != nil {
				t.Fatal(err)
			}
			_, err = file.Write(w.Body.Bytes())
			file.Close()
			if err != nil {
				t.Fatal(err)
			}
		}
		switch stage {
		case "consent":
			act(t, h.session, "allow")
		case "roots", "accounts":
			act(t, h.session, "choose", h.session.View().Choices[0].ID)
		case "presets":
			act(t, h.session, "preview", h.session.View().Choices[0].ID)
		case "review":
			v := h.session.View()
			if err := h.session.Apply(context.Background(), Action{Revision: v.Revision, Decision: "approve", Digest: v.Digest}); err != nil {
				t.Fatal(err)
			}
		}
	}
}
