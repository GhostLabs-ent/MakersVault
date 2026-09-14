package presetui

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"runtime"
	"strings"
	"testing"
	"time"
)

func previewURL() string { return "http://127.0.0.1:12345/preset-preview/" + strings.Repeat("a", 64) }
func TestPreviewURLBoundary(t *testing.T) {
	good := previewURL()
	if !ValidPreviewURL(good) {
		t.Fatal("owned URL shape rejected")
	}
	for _, bad := range []string{"", "https" + good[4:], strings.Replace(good, "127.0.0.1", "localhost", 1), strings.Replace(good, ":12345", ":012345", 1), strings.Replace(good, ":12345", ":0", 1), strings.Replace(good, ":12345", ":65536", 1), good + "?", good + "#x", good + "?x=y", good + "/", strings.Replace(good, "/preset-preview/", "/preset-preview/../", 1), strings.Replace(good, "127.0.0.1", "user@127.0.0.1", 1), strings.Replace(good, "aaaa", "AAAA", 1), strings.Replace(good, "aaaa", "%61aaa", 1), "file:///private", "javascript:alert(1)", "--flag", good + "\x00"} {
		if ValidPreviewURL(bad) {
			t.Fatal("unsafe URL accepted")
		}
	}
}

func TestUIRejectsAmbiguousFramesBeforeAction(t *testing.T) {
	frames := []string{`null`, `[]`, `{}`, `{"Version":1,"Version":1}`, `{"Version":1,"version":1}`, `{"Version":1,"Verſion":1}`, `{"Version":1,"Operation":null}`, `{"Version":1,"Operation":[]}`, `{"Version":1,"Operation":{}}`, `{"Version":1,"Operation":"folder","Path":"C:\\private"}`, `{"Version":1,"Operation":"folder","URL":"x"}`, `{"Version":1.0,"Operation":"folder"}`, `{"Version":2,"Operation":"folder"}`, `{"Version":1,"Operation":"folder"} {}`, `{"Version":1,"Operation":"shell"}`, strings.Repeat("x", MaxRequestBytes+1), "{\"Version\":1,\"Operation\":\"\xff\"}"}
	for _, frame := range frames {
		var out bytes.Buffer
		serve(strings.NewReader(frame), &out, "windows", func(request) (string, error) { t.Fatal("invalid frame reached native action"); return "", nil })
		var res response
		if json.Unmarshal(out.Bytes(), &res) != nil || res.Code != "ui_request_invalid" || res.Path != "" {
			t.Fatal("invalid frame not redacted")
		}
	}
}

func TestUIResponseAuthorityAndAtomicity(t *testing.T) {
	folder := request{Version: 1, Operation: "folder"}
	browser := request{Version: 1, Operation: "browser", URL: previewURL()}
	for _, tc := range []struct {
		req  request
		path string
		err  error
		code Code
	}{
		{folder, `C:\Users\Fixture\BambuStudio`, nil, ""},
		{folder, `\\server\share`, nil, "ui_selection_rejected"},
		{folder, `C:\`, nil, "ui_selection_rejected"},
		{folder, `C:\Users\..\private`, nil, "ui_selection_rejected"},
		{folder, `C:\private`, errors.New("PRIVATE_DIAGNOSTIC"), "ui_unavailable"},
		{folder, `C:\private`, Code("ui_cancelled"), "ui_cancelled"},
		{browser, "", nil, ""}, {browser, `C:\private`, nil, "ui_selection_rejected"},
	} {
		data, _ := json.Marshal(tc.req)
		var out bytes.Buffer
		serve(bytes.NewReader(data), &out, "windows", func(request) (string, error) { return tc.path, tc.err })
		var res response
		_ = json.Unmarshal(out.Bytes(), &res)
		if res.Code != tc.code || (tc.code != "" && res.Path != "") {
			t.Fatal("partial or incorrect response")
		}
		path, err := decodeResponse(out.Bytes(), tc.req, "windows")
		if tc.code == "" {
			if err != nil || path != tc.path {
				t.Fatal("valid response refused")
			}
		} else if err != tc.code || path != "" {
			t.Fatal("error response not atomic")
		}
	}
	for _, raw := range []string{`{"Version":1,"Code":"PRIVATE_DIAGNOSTIC"}`, `{"Version":1,"Path":"C:\\private","Code":"ui_cancelled"}`, `{"Version":1,"Path":"/private"}`, `{"Version":1,"Path":"C:\\private","path":"C:\\other"}`, `{"Version":1,"Path":null}`, `{"Version":1,"Code":"","Code":""}`} {
		if _, err := decodeResponse([]byte(raw), folder, "windows"); err != Code("ui_response_invalid") {
			t.Fatal("invalid result accepted")
		}
	}
	if _, err := decodeResponse([]byte(`{"Version":1}`), browser, "linux"); err != Code("ui_response_invalid") {
		t.Fatal("unsupported success accepted")
	}
	b, _ := json.Marshal(Folder{path: `C:\private`})
	if string(b) != "{}" {
		t.Fatal("local authority serialized")
	}
}

func TestUIServePlatformAndIOFailures(t *testing.T) {
	for _, platform := range []string{"linux", "darwin", "unknown"} {
		var out bytes.Buffer
		serve(strings.NewReader(`{"Version":1,"Operation":"folder"}`), &out, platform, func(request) (string, error) { t.Fatal("unsupported action executed"); return "", nil })
		if !strings.Contains(out.String(), "ui_platform_unsupported") {
			t.Fatal("unsupported platform not refused")
		}
	}
	if serve(strings.NewReader(`{}`), failedWriter{}, "windows", nil) != 1 {
		t.Fatal("write failure ignored")
	}
}

type failedWriter struct{}

func (failedWriter) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

func TestUIEnvironmentAllowlist(t *testing.T) {
	keys := []string{}
	values := uiEnvironment("windows", func(k string) string { keys = append(keys, k); return "synthetic" })
	if strings.Join(keys, ",") != "SystemRoot,SystemDrive,USERPROFILE,LOCALAPPDATA,APPDATA,TEMP,TMP" || len(values) != 8 {
		t.Fatal("desktop environment widened")
	}
	if got := uiEnvironment("linux", func(string) string { t.Fatal("unsupported lookup"); return "" }); len(got) != 1 {
		t.Fatal("environment inherited")
	}
}

func TestUIPublicPreflightNeverLaunches(t *testing.T) {
	if err := OpenBrowser(nil, previewURL()); err != Code("ui_unavailable") {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := PickFolder(ctx); err != Code("ui_cancelled") {
		t.Fatal(err)
	}
	ctx, cancel = context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	if err := OpenBrowser(ctx, previewURL()); err != Code("ui_timeout") {
		t.Fatal(err)
	}
	if err := OpenBrowser(context.Background(), "file:///private"); err != Code("ui_request_invalid") {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" {
		if _, err := PickFolder(context.Background()); err != Code("ui_platform_unsupported") {
			t.Fatal(err)
		}
		if err := OpenBrowser(context.Background(), previewURL()); err != Code("ui_platform_unsupported") {
			t.Fatal(err)
		}
	}
	if len(uiSlot) != 0 {
		t.Fatal("preflight acquired slot")
	}
}

func FuzzNativeUIFrame(f *testing.F) {
	for _, s := range []string{`{"Version":1,"Operation":"folder"}`, `{"Version":1,"Code":"ui_cancelled"}`, `null`, `[]`} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s string) {
		if len(s) > MaxResponseBytes+1 {
			return
		}
		var req request
		_ = decode([]byte(s), &req, MaxRequestBytes)
		_, _ = decodeResponse([]byte(s), request{Version: 1, Operation: "folder"}, "windows")
	})
}
func FuzzPreviewURL(f *testing.F) {
	f.Add(previewURL())
	f.Add("file:///private")
	f.Add("http://localhost:1/")
	f.Fuzz(func(t *testing.T, s string) { _ = ValidPreviewURL(s) })
}
