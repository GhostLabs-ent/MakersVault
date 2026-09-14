//go:build windows && (amd64 || arm64)

package presetfiles

import (
	"context"
	"runtime"
	"syscall"
	"unsafe"
)

// Fixed System32 libraries only. Never use PATH/current-directory DLL search or
// shell commands. Loading and this known-folder call still need native proof.
func systemHintDLL(name string) (syscall.Handle, error) {
	proc := winKernel.NewProc("LoadLibraryExW")
	if proc.Find() != nil {
		return 0, Code("source_hint_unavailable")
	}
	wide, _ := syscall.UTF16PtrFromString(name)
	handle, _, _ := proc.Call(uintptr(unsafe.Pointer(wide)), 0, 0x800) // LOAD_LIBRARY_SEARCH_SYSTEM32
	runtime.KeepAlive(wide)
	if handle == 0 {
		return 0, Code("source_hint_unavailable")
	}
	return syscall.Handle(handle), nil
}

func nativeLocationHints(ctx context.Context) (LocationHints, error) {
	if err := check(ctx); err != nil {
		return LocationHints{}, err
	}
	shell, err := systemHintDLL("shell32.dll")
	if err != nil {
		return LocationHints{}, err
	}
	defer syscall.FreeLibrary(shell)
	ole, err := systemHintDLL("ole32.dll")
	if err != nil {
		return LocationHints{}, err
	}
	defer syscall.FreeLibrary(ole)
	getPath, err := syscall.GetProcAddress(shell, "SHGetKnownFolderPath")
	if err != nil {
		return LocationHints{}, Code("source_hint_unavailable")
	}
	free, err := syscall.GetProcAddress(ole, "CoTaskMemFree")
	if err != nil {
		return LocationHints{}, Code("source_hint_unavailable")
	}
	// FOLDERID_RoamingAppData, current-user NULL token, KF_FLAG_DONT_VERIFY.
	// No CREATE, INIT, DEFAULT_PATH or guessed environment-variable fallback.
	folder := syscall.GUID{Data1: 0x3eb685db, Data2: 0x65f9, Data3: 0x4cf6,
		Data4: [8]byte{0xa0, 0x3a, 0xe3, 0xef, 0x65, 0x72, 0x9f, 0x3d}}
	var result *uint16
	status, _, _ := syscall.SyscallN(getPath, uintptr(unsafe.Pointer(&folder)), 0x4000, 0, uintptr(unsafe.Pointer(&result)))
	runtime.KeepAlive(folder)
	// Microsoft requires freeing a returned allocation even on failure.
	if result != nil {
		defer syscall.SyscallN(free, uintptr(unsafe.Pointer(result)))
	}
	if status != 0 || result == nil {
		return LocationHints{}, Code("source_hint_unavailable")
	}
	words := make([]uint16, 0, 256)
	for i := 0; i <= 4096; i++ {
		word := *(*uint16)(unsafe.Add(unsafe.Pointer(result), uintptr(i)*2))
		if word == 0 {
			return LocationHints{Platform: "windows", RoamingAppData: syscall.UTF16ToString(words)}, check(ctx)
		}
		words = append(words, word)
	}
	return LocationHints{}, Code("source_hint_unavailable")
}
