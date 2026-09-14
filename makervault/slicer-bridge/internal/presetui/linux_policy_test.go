package presetui

import (
	"context"
	"reflect"
	"strings"
	"testing"
)

func desktopFixture() map[string]string {
	return map[string]string{"HOME": "/home/fixture", "XDG_RUNTIME_DIR": "/run/user/1000", "DISPLAY": ":0"}
}
func TestLinuxFixedCommandPolicy(t *testing.T) {
	browser, err := linuxCommand(request{Version: 1, Operation: "browser", URL: previewURL()})
	if err != nil || browser.name != "gio" || !reflect.DeepEqual(browser.args, []string{"gio", "open", "--", previewURL()}) {
		t.Fatal("browser invocation widened")
	}
	folder, err := linuxCommand(request{Version: 1, Operation: "folder"})
	if err != nil || folder.name != "zenity" || !reflect.DeepEqual(folder.args, []string{"zenity", "--file-selection", "--directory", "--title=MakersVault: choose a Bambu Studio data folder", "--ok-label=Use this folder"}) {
		t.Fatal("folder invocation widened")
	}
	for _, req := range []request{{Version: 1, Operation: "shell"}, {Version: 1, Operation: "browser", URL: "file:///private"}, {Version: 1, Operation: "folder", URL: previewURL()}} {
		if _, err := linuxCommand(req); err != Code("ui_request_invalid") {
			t.Fatal("invalid command accepted")
		}
	}
}
func TestLinuxDesktopEnvironmentBoundary(t *testing.T) {
	values := desktopFixture()
	values["PATH"] = "/private"
	values["LD_PRELOAD"] = "/private/injection"
	values["BROWSER"] = "private-command"
	values["GTK_MODULES"] = "private"
	values["MAKERSVAULT_SECRET"] = "private"
	env, err := linuxEnvironment(func(k string) string { return values[k] })
	expected := []string{"PATH=/usr/bin:/bin", "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "GIO_USE_VFS=local", "HOME=/home/fixture", "XDG_RUNTIME_DIR=/run/user/1000", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", "DISPLAY=:0"}
	if err != nil || !reflect.DeepEqual(env, expected) {
		t.Fatal("native environment widened")
	}
	keys := []string{}
	_ = uiEnvironment("linux", func(k string) string { keys = append(keys, k); return values[k] })
	if strings.Join(keys, ",") != "HOME,XDG_CONFIG_HOME,XDG_DATA_HOME,XDG_RUNTIME_DIR,DISPLAY,WAYLAND_DISPLAY,XAUTHORITY,DBUS_SESSION_BUS_ADDRESS" {
		t.Fatal("worker environment widened")
	}
	for _, pair := range [][2]string{{"HOME", ""}, {"HOME", "/"}, {"XDG_RUNTIME_DIR", ""}, {"XDG_RUNTIME_DIR", "/run/../private"}, {"XDG_RUNTIME_DIR", "/run/a,b"}, {"XDG_RUNTIME_DIR", "/run/" + strings.Repeat("a", 108)}, {"DISPLAY", "remote.example:0"}, {"DISPLAY", "127.0.0.1:0"}, {"DISPLAY", ":"}, {"DISPLAY", ":0.0.0"}, {"DISPLAY", ""}, {"WAYLAND_DISPLAY", "../socket"}, {"WAYLAND_DISPLAY", "/run/user/1000/socket"}, {"XAUTHORITY", "relative"}, {"DBUS_SESSION_BUS_ADDRESS", "autolaunch:"}, {"DBUS_SESSION_BUS_ADDRESS", "tcp:host=localhost,port=1"}, {"DBUS_SESSION_BUS_ADDRESS", "unix:abstract=private"}, {"DBUS_SESSION_BUS_ADDRESS", "unix:path=/other/bus"}, {"DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus;autolaunch:"}, {"DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus,guid=bad"}} {
		values := desktopFixture()
		values[pair[0]] = pair[1]
		if env, err := linuxEnvironment(func(k string) string { return values[k] }); err != Code("ui_unavailable") || env != nil {
			t.Fatalf("unsafe environment accepted: %s", pair[0])
		}
	}
	for _, display := range []string{":0", ":10.1", "unix:0"} {
		if !localDisplay(display) {
			t.Fatal("local X11 syntax refused")
		}
	}
	values = desktopFixture()
	delete(values, "DISPLAY")
	values["WAYLAND_DISPLAY"] = "wayland-0"
	values["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus,guid=" + strings.Repeat("a", 32)
	if _, err := linuxEnvironment(func(k string) string { return values[k] }); err != nil {
		t.Fatal("Wayland environment refused")
	}
}
func TestLinuxNativeResultBoundary(t *testing.T) {
	folder := request{Version: 1, Operation: "folder"}
	browser := request{Version: 1, Operation: "browser", URL: previewURL()}
	if root, err := decodeLinuxResult([]byte("/home/fixture/Bambu Studio\n"), folder); err != nil || root != "/home/fixture/Bambu Studio" {
		t.Fatal("folder result changed")
	}
	if root, err := decodeLinuxResult(nil, browser); err != nil || root != "" {
		t.Fatal("empty browser success rejected")
	}
	for _, data := range []string{"", "/private", "/\n", "relative\n", "/a/../private\n", "/private\n/other\n", "/private\n\n", "file:///private\n", "/private\r\n", "/private\x00\n", "/private\xff\n", strings.Repeat("a", MaxResponseBytes+1), `{"Version":1}`, `{"Version":1,"Code":"ui_unavailable","Path":"/private"}`} {
		if path, err := decodeLinuxResult([]byte(data), folder); err == nil || path != "" {
			t.Fatal("ambiguous folder accepted")
		}
	}
	for _, data := range []string{"\n", "native output", "/private\n", `{"Version":1}`} {
		if _, err := decodeLinuxResult([]byte(data), browser); err == nil {
			t.Fatal("unexpected browser output accepted")
		}
	}
	if root, err := decodeLinuxResult([]byte(`{"Version":1,"Code":"ui_unavailable","Path":""}`), folder); err != Code("ui_unavailable") || root != "" {
		t.Fatal("pre-exec error not redacted")
	}
}
func TestLinuxNativeCancelAndDiagnosticPrecedence(t *testing.T) {
	for _, tc := range []struct {
		mode   string
		picker bool
		want   Code
	}{{"native-cancel", true, "ui_cancelled"}, {"native-cancel", false, "ui_failed"}, {"native-cancel-diagnostic", true, "ui_failed"}} {
		data, err := superviseExit(context.Background(), fixtureCommand(t, tc.mode), nil, tc.picker)
		if data != nil || err != tc.want {
			t.Fatal("native exit classification or atomicity failed")
		}
		waitIdle(t)
	}
	data, err := superviseExit(context.Background(), fixtureCommand(t, "native-folder"), nil, true)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := decodeLinuxResult(data, request{Version: 1, Operation: "folder"}); err != nil {
		t.Fatal(err)
	}
}
func FuzzLinuxUIResult(f *testing.F) {
	for _, s := range []string{"/home/fixture/模型\n", "/private\n/other\n", `{"Version":1,"Code":"ui_unavailable"}`, ""} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s string) {
		if len(s) > MaxResponseBytes+1 {
			return
		}
		_, _ = decodeLinuxResult([]byte(s), request{Version: 1, Operation: "folder"})
	})
}
