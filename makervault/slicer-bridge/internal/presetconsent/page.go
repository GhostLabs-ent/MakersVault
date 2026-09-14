package presetconsent

import (
	"bytes"
	"html/template"
	"io"
	"mime"
	"net"
	"net/http"
	"strconv"
)

const MaxFormBytes = 16 << 10
const MaxPageBytes = 4 << 20

// LocalHandler never listens or opens a browser. StartLocal supplies the bounded
// numeric-loopback host, without request/URL/body logging, and tears it down on
// expiry/revoke. Native browser launch and production integration remain separate.
// A website-origin trust entry does not bypass this separate local consent page.
type LocalHandler struct {
	session          *Session
	host, path, csrf string
}

func NewLocalHandler(session *Session, host string) (*LocalHandler, error) {
	ip, port, err := net.SplitHostPort(host)
	number, numberErr := strconv.Atoi(port)
	if session == nil || err != nil || ip != "127.0.0.1" || numberErr != nil || number < 1 || number > 65535 ||
		host != net.JoinHostPort(ip, strconv.Itoa(number)) {
		return nil, Code("consent_configuration_invalid")
	}
	return &LocalHandler{session, host, "/preset-preview/" + token(), token()}, nil
}

// URL contains an ephemeral local bearer nonce; never send it to the vault/logs.
func (h *LocalHandler) URL() string { return "http://" + h.host + h.path }

func (h *LocalHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	// no-referrer makes native form POSTs send Origin:null. Keep exact Origin
	// enforcement while withholding the nonce-bearing Referer from other origins.
	w.Header().Set("Referrer-Policy", "same-origin")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
	remote, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || net.ParseIP(remote) == nil || !net.ParseIP(remote).IsLoopback() || r.Host != h.host ||
		r.URL.Path != h.path || r.URL.RawPath != "" || r.URL.RawQuery != "" || r.URL.ForceQuery ||
		(r.URL.IsAbs() && (r.URL.Scheme != "http" || r.URL.Host != h.host)) {
		http.Error(w, "Local request rejected", http.StatusForbidden)
		return
	}
	if len(r.Header.Values("Origin")) > 1 || (r.Header.Get("Origin") != "" && r.Header.Get("Origin") != "http://"+h.host) {
		http.Error(w, "Local request rejected", http.StatusForbidden)
		return
	}
	if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "none" && site != "same-origin" {
		http.Error(w, "Local request rejected", http.StatusForbidden)
		return
	}
	status := http.StatusOK
	if r.Method == http.MethodPost {
		media, params, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if err != nil || media != "application/x-www-form-urlencoded" || len(params) != 0 || r.Header.Get("Origin") != "http://"+h.host {
			http.Error(w, "Local form rejected", http.StatusForbidden)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, MaxFormBytes)
		if err := r.ParseForm(); err != nil {
			http.Error(w, "Invalid form", http.StatusBadRequest)
			return
		}
		for key, values := range r.PostForm {
			if key != "csrf" && key != "revision" && key != "decision" && key != "choice" && key != "digest" {
				http.Error(w, "Invalid form", http.StatusBadRequest)
				return
			}
			if (key == "choice" && len(values) > 100) || (key != "choice" && len(values) != 1) {
				http.Error(w, "Invalid form", http.StatusBadRequest)
				return
			}
		}
		if r.PostForm.Get("csrf") != h.csrf {
			http.Error(w, "Local form rejected", http.StatusForbidden)
			return
		}
		err = h.session.Apply(r.Context(), Action{Revision: r.PostForm.Get("revision"), Decision: r.PostForm.Get("decision"),
			Digest: r.PostForm.Get("digest"), Choices: r.PostForm["choice"]})
		if err != nil {
			status = http.StatusConflict
		}
	} else if r.Method != http.MethodGet {
		w.Header().Set("Allow", "GET, POST")
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	view := h.session.View()
	if status != http.StatusOK && view.Warning == "" {
		view.Warning = "This form is stale, busy or invalid. Review the current step before retrying."
	}
	data := struct {
		View
		CSRF, Path string
	}{view, h.csrf, h.path}
	var buffer boundedPage
	if err := page.Execute(&buffer, data); err != nil {
		http.Error(w, "Local preview exceeds display limits", http.StatusRequestEntityTooLarge)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write(buffer.Bytes())
}

type boundedPage struct{ bytes.Buffer }

func (b *boundedPage) WriteString(text string) (int, error) { return b.Write([]byte(text)) }
func (b *boundedPage) Write(p []byte) (int, error) {
	if len(p) > MaxPageBytes-b.Len() {
		return 0, io.ErrShortBuffer
	}
	return b.Buffer.Write(p)
}

var page = template.Must(template.New("local-preview").Parse(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MakersVault · Local printer presets</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#15171c;color:#edeef2;font:16px/1.55 system-ui,sans-serif}main{max-width:900px;margin:6vh auto;padding:24px}.panel{border:1px solid #343844;border-radius:16px;background:#20232b;padding:24px}h1{font-size:1.7rem;margin:8px 0}h2{font-size:1.2rem}.eyebrow,.muted{color:#b7bdcc}.eyebrow{font-size:.8rem;letter-spacing:.08em;text-transform:uppercase}.origin,pre{overflow-wrap:anywhere;white-space:pre-wrap;background:#15171c;border-radius:8px;padding:12px}.choices{max-height:44vh;overflow:auto;border:1px solid #454b59;border-radius:10px;padding:8px}.choice{display:flex;align-items:start;gap:12px;padding:12px;border-radius:6px;overflow-wrap:anywhere}.choice:hover{background:#2c3240}input{width:20px;height:20px;flex:none}button{min-height:44px;padding:10px 18px;margin:12px 8px 0 0;border:1px solid #697389;border-radius:8px;background:#303644;color:inherit;font:inherit;cursor:pointer}.primary{background:#356ce6;border-color:#5688f0}:focus-visible{outline:3px solid #91b8ff;outline-offset:3px}.warning{color:#ffd39b}pre{max-height:50vh;overflow:auto;font-size:.85rem}fieldset{border:0;padding:0;margin:0}legend{padding-bottom:8px}@media(max-width:600px){main{margin:0;padding:12px}.panel{padding:16px}button{width:100%;margin-right:0}}
.muted{overflow-wrap:anywhere}.refresh{display:inline-block;min-height:44px;padding:10px;color:#91b8ff}
</style></head><body><main><p class="eyebrow">MakersVault bridge · Local preview only</p><section class="panel">
<h1>Printer preset preview</h1><p>Requested vault address (not yet authenticated by this preview):</p><p class="origin">{{.Origin}}</p>
<p class="muted">Nothing is sent or saved by this flow. File-download trust does not approve sharing printer presets. These are slicer presets, not proof of owned or connected printers.</p>
{{if .Warning}}<p role="alert" class="warning">{{.Warning}}</p>{{end}}
{{if .Busy}}<p role="status">{{if .Picking}}{{if .PickerStopping}}Cancelling folder selection…{{else}}Choose a Bambu Studio data folder in the dialog on this workstation. No presets have been read by this selection.{{end}}{{else}}Reading local metadata…{{end}} Refresh to see the result, or cancel below.</p>
<a class="refresh" href="{{.Path}}">Refresh status</a>
{{if and .Picking (not .PickerStopping)}}<form method="post" action="{{.Path}}"><input type="hidden" name="csrf" value="{{.CSRF}}"><input type="hidden" name="revision" value="{{.Revision}}"><button name="decision" value="stop-picker">Cancel folder selection</button></form>{{end}}{{else}}
{{if eq .Stage "consent"}}<h2>Allow local reading for this preview?</h2><p>Look up Bambu Studio folder hints, then choose a folder and an account or system-only presets. Only selected normalized printer metadata can reach the review. Account folders stay local; labels may contain private text.</p>
<form method="post" action="{{.Path}}"><input type="hidden" name="csrf" value="{{.CSRF}}"><input type="hidden" name="revision" value="{{.Revision}}"><button class="primary" name="decision" value="allow">Allow local reading</button></form>
{{else if or (eq .Stage "roots") (eq .Stage "accounts") (eq .Stage "presets")}}
<form method="post" action="{{.Path}}"><input type="hidden" name="csrf" value="{{.CSRF}}"><input type="hidden" name="revision" value="{{.Revision}}"><fieldset><legend>{{if eq .Stage "roots"}}Choose a data folder (existence unverified){{else if eq .Stage "accounts"}}Choose an account folder or system-only presets{{else}}Choose up to 100 printer presets for review{{end}}</legend>
<div class="choices">{{range .Choices}}<label class="choice"><input {{if eq $.Stage "presets"}}type="checkbox"{{else}}type="radio" required{{end}} name="choice" value="{{.ID}}"><span>{{.Label}}</span></label>{{else}}<p>No selectable presets found. Restart to choose another source.</p>{{end}}</div></fieldset>
{{if .Choices}}<button class="primary" name="decision" value="{{if eq .Stage "presets"}}preview{{else}}choose{{end}}">{{if eq .Stage "presets"}}Review selected metadata{{else if eq .Stage "accounts"}}Read printer presets{{else}}Use this folder{{end}}</button>{{end}}</form>
{{else if eq .Stage "review"}}<h2>Review the exact metadata</h2><p>Check every name and value below. Null fields and reason codes mean missing or unsupported information; this is not print-ready certification. No account-folder name or path is intentionally included; user-authored labels can still contain private text.</p>
<pre tabindex="0" aria-label="Exact normalized preset metadata">{{.Preview}}</pre><p class="muted">Review SHA-256: {{.Digest}}</p>
<form method="post" action="{{.Path}}"><input type="hidden" name="csrf" value="{{.CSRF}}"><input type="hidden" name="revision" value="{{.Revision}}"><input type="hidden" name="digest" value="{{.Digest}}"><button class="primary" name="decision" value="approve">Approve local preview</button></form>
{{else if eq .Stage "approved"}}<h2>Local preview approved</h2><p>Nothing has been sent to MakersVault. Remote approval and import are separate, currently unavailable steps.</p>
{{else if eq .Stage "failed"}}<h2>Preview unavailable</h2><p>Restart to make a new explicit selection.</p>
{{else}}<h2>Local preview closed</h2><p>This preview is cancelled, expired or already consumed. Start a new request to continue.</p>{{end}}{{end}}
{{if .CanPick}}<p>Choose a custom Bambu Studio data folder on this workstation instead. The dialog may browse local folders; MakersVault will not read presets until you confirm the selected folder. If unavailable, no other folder is scanned automatically.</p>
<form method="post" action="{{.Path}}"><input type="hidden" name="csrf" value="{{.CSRF}}"><input type="hidden" name="revision" value="{{.Revision}}"><button name="decision" value="browse">{{if eq .Stage "consent"}}Allow local reading and choose a folder{{else}}Choose a custom folder{{end}}</button></form>{{end}}
{{if and (ne .Stage "expired") (ne .Stage "cancelled") (ne .Stage "consumed")}}<form method="post" action="{{.Path}}"><input type="hidden" name="csrf" value="{{.CSRF}}"><input type="hidden" name="revision" value="{{.Revision}}">{{if not .Busy}}<button name="decision" value="restart">Start over</button>{{end}}<button name="decision" value="cancel">Cancel</button></form>{{end}}
</section></main></body></html>`))
