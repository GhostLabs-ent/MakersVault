//go:build windows && (amd64 || arm64)

package presetui

import (
	"testing"
	"unsafe"
)

// ABI/flag checks only: no DLL loads, browser, dialog or filesystem action.
func TestWindowsUILayoutAndPolicy(t *testing.T) {
	if unsafe.Sizeof(shellExecuteInfo{}) != 112 || unsafe.Offsetof(shellExecuteInfo{}.Show) != 48 || unsafe.Offsetof(shellExecuteInfo{}.HotKey) != 88 || unsafe.Offsetof(shellExecuteInfo{}.Process) != 104 {
		t.Fatal("ShellExecute ABI drift")
	}
	if browserFlags != 0x4540 || folderFlags != 0x02301868 {
		t.Fatal("UI policy flags drift")
	}
	if failed(0) || failed(1) || !failed(0x80004005) {
		t.Fatal("HRESULT classification")
	}
}
