//go:build windows && (amd64 || arm64)

package presetui

import (
	"runtime"
	"syscall"
	"unsafe"
)

// kernel32 is a Windows KnownDLL; all other library loads use System32 only.
var kernel = syscall.NewLazyDLL("kernel32.dll")

func systemDLL(name string) (syscall.Handle, error) {
	if name != "ole32.dll" && name != "shell32.dll" {
		return 0, Code("ui_unavailable")
	}
	load := kernel.NewProc("LoadLibraryExW")
	if load.Find() != nil {
		return 0, Code("ui_unavailable")
	}
	wide, _ := syscall.UTF16PtrFromString(name)
	h, _, _ := load.Call(uintptr(unsafe.Pointer(wide)), 0, 0x800) // LOAD_LIBRARY_SEARCH_SYSTEM32
	runtime.KeepAlive(wide)
	if h == 0 {
		return 0, Code("ui_unavailable")
	}
	return syscall.Handle(h), nil
}

type comObject struct{ table *[29]uintptr }

// Only scalar arguments belong in this helper. Go pointers must be converted in
// the SyscallN expression itself, so the compiler preserves them across the call.
func (o *comObject) scalar(slot int, arg uintptr) uintptr {
	result, _, _ := syscall.SyscallN(o.table[slot], uintptr(unsafe.Pointer(o)), arg)
	runtime.KeepAlive(o)
	return result
}
func (o *comObject) release() {
	syscall.SyscallN(o.table[2], uintptr(unsafe.Pointer(o)))
	runtime.KeepAlive(o)
}
func failed(status uintptr) bool { return int32(status) < 0 }

// Layout is the 64-bit Windows SHELLEXECUTEINFOW ABI, not a portable C struct.
type shellExecuteInfo struct {
	Size, Mask                        uint32
	Window                            uintptr
	Verb, File, Parameters, Directory *uint16
	Show                              int32
	Instance, IDList                  uintptr
	Class                             *uint16
	ClassKey                          uintptr
	HotKey                            uint32
	Icon, Process                     uintptr
}

// Both supported architectures use the same 64-bit ABI. Compile-time equality.
var _ [112 - unsafe.Sizeof(shellExecuteInfo{})]byte
var _ [unsafe.Sizeof(shellExecuteInfo{}) - 112]byte
var _ [104 - unsafe.Offsetof(shellExecuteInfo{}.Process)]byte
var _ [unsafe.Offsetof(shellExecuteInfo{}.Process) - 104]byte

const browserFlags = 0x40 | 0x100 | 0x400 | 0x4000 // NOCLOSEPROCESS, NOASYNC, FLAG_NO_UI, UNICODE
const folderFlags = 0x8 | 0x20 | 0x40 | 0x800 | 0x1000 | 0x100000 | 0x200000 | 0x2000000

func nativeAction(req request) (string, error) {
	if !validRequest(req) {
		return "", Code("ui_request_invalid")
	}
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	ole, err := systemDLL("ole32.dll")
	if err != nil {
		return "", err
	}
	defer syscall.FreeLibrary(ole)
	init, err := syscall.GetProcAddress(ole, "CoInitializeEx")
	if err != nil {
		return "", Code("ui_unavailable")
	}
	uninit, err := syscall.GetProcAddress(ole, "CoUninitialize")
	if err != nil {
		return "", Code("ui_unavailable")
	}
	status, _, _ := syscall.SyscallN(init, 0, 6) // STA | DISABLE_OLE1DDE
	if failed(status) {
		return "", Code("ui_unavailable")
	}
	defer syscall.SyscallN(uninit)
	if req.Operation == "browser" {
		return "", openPreview(req.URL)
	}
	return chooseFolder(ole)
}

func openPreview(target string) error {
	if !ValidPreviewURL(target) {
		return Code("ui_request_invalid")
	}
	shell, err := systemDLL("shell32.dll")
	if err != nil {
		return err
	}
	defer syscall.FreeLibrary(shell)
	open, err := syscall.GetProcAddress(shell, "ShellExecuteExW")
	if err != nil {
		return Code("ui_unavailable")
	}
	verb, _ := syscall.UTF16PtrFromString("open")
	file, _ := syscall.UTF16PtrFromString(target)
	info := shellExecuteInfo{Mask: browserFlags, Verb: verb, File: file, Show: 1}
	info.Size = uint32(unsafe.Sizeof(info))
	result, _, _ := syscall.SyscallN(open, uintptr(unsafe.Pointer(&info)))
	runtime.KeepAlive(verb)
	runtime.KeepAlive(file)
	runtime.KeepAlive(&info)
	// This handle is NOT permission to terminate/wait for a potentially shared browser.
	if info.Process != 0 {
		_ = syscall.CloseHandle(syscall.Handle(info.Process))
	}
	if result == 0 {
		return Code("ui_unavailable")
	}
	// Shell acceptance only. NOASYNC is not a URI-load/readiness guarantee.
	return nil
}

func chooseFolder(ole syscall.Handle) (string, error) {
	create, err := syscall.GetProcAddress(ole, "CoCreateInstance")
	if err != nil {
		return "", Code("ui_unavailable")
	}
	free, err := syscall.GetProcAddress(ole, "CoTaskMemFree")
	if err != nil {
		return "", Code("ui_unavailable")
	}
	class := syscall.GUID{Data1: 0xdc1c5a9c, Data2: 0xe88a, Data3: 0x4dde, Data4: [8]byte{0xa5, 0xa1, 0x60, 0xf8, 0x2a, 0x20, 0xae, 0xf7}}
	iface := syscall.GUID{Data1: 0xd57c7288, Data2: 0xd4ad, Data3: 0x4768, Data4: [8]byte{0xbe, 0x02, 0x9d, 0x96, 0x95, 0x32, 0xd9, 0x60}}
	var dialog *comObject
	status, _, _ := syscall.SyscallN(create, uintptr(unsafe.Pointer(&class)), 0, 1, uintptr(unsafe.Pointer(&iface)), uintptr(unsafe.Pointer(&dialog))) // CLSCTX_INPROC_SERVER
	runtime.KeepAlive(class)
	runtime.KeepAlive(iface)
	if dialog != nil {
		defer dialog.release()
	}
	if failed(status) || dialog == nil {
		return "", Code("ui_unavailable")
	}
	// Single folder, existing filesystem result, no link dereference/recent-doc add,
	// explicit interaction required. These flags do NOT confine Shell UI browsing.
	if failed(dialog.scalar(9, folderFlags)) {
		return "", Code("ui_unavailable")
	}
	title, _ := syscall.UTF16PtrFromString("MakersVault: choose a Bambu Studio data folder")
	status, _, _ = syscall.SyscallN(dialog.table[17], uintptr(unsafe.Pointer(dialog)), uintptr(unsafe.Pointer(title)))
	runtime.KeepAlive(title)
	if failed(status) {
		return "", Code("ui_unavailable")
	}
	status = dialog.scalar(3, 0) // Show(NULL), user selection only; no remote owner HWND
	if uint32(status) == 0x800704c7 {
		return "", Code("ui_cancelled")
	}
	if failed(status) {
		return "", Code("ui_unavailable")
	}
	var item *comObject
	status, _, _ = syscall.SyscallN(dialog.table[20], uintptr(unsafe.Pointer(dialog)), uintptr(unsafe.Pointer(&item)))
	if item != nil {
		defer item.release()
	}
	if failed(status) || item == nil {
		return "", Code("ui_unavailable")
	}
	var value *uint16
	status, _, _ = syscall.SyscallN(item.table[5], uintptr(unsafe.Pointer(item)), 0x80058000, uintptr(unsafe.Pointer(&value))) // IShellItem.GetDisplayName(SIGDN_FILESYSPATH)
	if value != nil {
		defer syscall.SyscallN(free, uintptr(unsafe.Pointer(value)))
	}
	if failed(status) || value == nil {
		return "", Code("ui_selection_rejected")
	}
	words := make([]uint16, 0, 256)
	for i := 0; i <= 4096; i++ {
		word := *(*uint16)(unsafe.Add(unsafe.Pointer(value), uintptr(i)*2))
		if word == 0 {
			root := syscall.UTF16ToString(words)
			if !validRoot("windows", root) {
				return "", Code("ui_selection_rejected")
			}
			return root, nil
		}
		words = append(words, word)
	}
	return "", Code("ui_selection_rejected")
}
