package presetui

import (
	"bytes"
	"strings"
	"unicode/utf8"
)

// Pure policy is compiled/tested on every platform; no environment lookup here.
var linuxDesktopKeys = []string{"HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"}

type linuxTool struct {
	name string
	args []string
}

func linuxCommand(req request) (linuxTool, error) {
	if !validRequest(req) {
		return linuxTool{}, Code("ui_request_invalid")
	}
	if req.Operation == "browser" {
		return linuxTool{"gio", []string{"gio", "open", "--", req.URL}}, nil
	}
	return linuxTool{"zenity", []string{"zenity", "--file-selection", "--directory", "--title=MakersVault: choose a Bambu Studio data folder", "--ok-label=Use this folder"}}, nil
}

func localDisplay(s string) bool {
	s = strings.TrimPrefix(s, "unix")
	if !strings.HasPrefix(s, ":") || len(s) > 32 {
		return false
	}
	parts := strings.Split(s[1:], ".")
	if len(parts) > 2 {
		return false
	}
	for _, part := range parts {
		if part == "" {
			return false
		}
		for _, c := range part {
			if c < '0' || c > '9' {
				return false
			}
		}
	}
	return true
}
func waylandName(s string) bool {
	if s == "" || s == "." || s == ".." || len(s) > 128 {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-' || c == '.') {
			return false
		}
	}
	return true
}
func linuxEnvironment(lookup func(string) string) ([]string, error) {
	values := []string{"PATH=/usr/bin:/bin", "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "GIO_USE_VFS=local"}
	for _, key := range []string{"HOME", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XAUTHORITY"} {
		value := lookup(key)
		if value == "" {
			if key == "HOME" || key == "XDG_RUNTIME_DIR" {
				return nil, Code("ui_unavailable")
			}
			continue
		}
		if !validRoot("linux", value) {
			return nil, Code("ui_unavailable")
		}
		values = append(values, key+"="+value)
	}
	// One conventional local session bus only: no tcp/abstract/exec/autolaunch,
	// multi-address fallback, percent escapes or unbounded inherited address data.
	runtimeDir := lookup("XDG_RUNTIME_DIR")
	for _, c := range runtimeDir {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.ContainsRune("/_-.", c)) {
			return nil, Code("ui_unavailable")
		}
	}
	expected := "unix:path=" + runtimeDir + "/bus"
	if len(runtimeDir+"/bus") > 107 {
		return nil, Code("ui_unavailable")
	}
	address := lookup("DBUS_SESSION_BUS_ADDRESS")
	if address != "" && address != expected {
		prefix := expected + ",guid="
		if !strings.HasPrefix(address, prefix) || len(address) != len(prefix)+32 {
			return nil, Code("ui_unavailable")
		}
		for _, c := range address[len(prefix):] {
			if !(c >= 'a' && c <= 'f' || c >= '0' && c <= '9') {
				return nil, Code("ui_unavailable")
			}
		}
	}
	values = append(values, "DBUS_SESSION_BUS_ADDRESS="+expected)
	display, wayland := lookup("DISPLAY"), lookup("WAYLAND_DISPLAY")
	if display == "" && wayland == "" {
		return nil, Code("ui_unavailable")
	}
	if display != "" {
		if !localDisplay(display) {
			return nil, Code("ui_unavailable")
		}
		values = append(values, "DISPLAY="+display)
	}
	if wayland != "" {
		if !waylandName(wayland) {
			return nil, Code("ui_unavailable")
		}
		values = append(values, "WAYLAND_DISPLAY="+wayland)
	}
	return values, nil
}

// Linux replaces the worker with the fixed native ELF, keeping the supervised PID.
// Its successful output is native tool output; errors before exec are JSON frames.
func decodeLinuxResult(data []byte, req request) (string, error) {
	if len(data) > MaxResponseBytes || !utf8.Valid(data) || !validRequest(req) {
		return "", Code("ui_response_invalid")
	}
	if bytes.HasPrefix(data, []byte("{")) {
		var r response
		if decode(data, &r, MaxResponseBytes) != nil || r.Code == "" || !allowedCode(r.Code) || r.Path != "" {
			return "", Code("ui_response_invalid")
		}
		return "", r.Code
	}
	if req.Operation == "browser" {
		if len(data) != 0 {
			return "", Code("ui_response_invalid")
		}
		return "", nil
	}
	if len(data) < 2 || data[len(data)-1] != '\n' {
		return "", Code("ui_response_invalid")
	}
	root := string(data[:len(data)-1]) // exactly one terminator; never trim/split/clean paths
	if strings.ContainsAny(root, "\r\n") || !validRoot("linux", root) {
		return "", Code("ui_selection_rejected")
	}
	return root, nil
}
