//go:build windows && (amd64 || arm64)

package presetfiles

import (
	"context"
	"os"
	"runtime"
	"strings"
	"syscall"
	"unsafe"
)

// Only KnownDLL system libraries, never a caller-supplied DLL or executable.
var (
	ntCreateFile  = syscall.NewLazyDLL("ntdll.dll").NewProc("NtCreateFile")
	winKernel     = syscall.NewLazyDLL("kernel32.dll")
	getDriveType  = winKernel.NewProc("GetDriveTypeW")
	getFinalPath  = winKernel.NewProc("GetFinalPathNameByHandleW")
	getVolumeInfo = winKernel.NewProc("GetVolumeInformationByHandleW")
	reOpenFile    = winKernel.NewProc("ReOpenFile")
)

const (
	objCaseInsensitive = 0x40
	objDontReparse     = 0x1000
	fileOpen           = 1
	fileDirectory      = 0x1
	fileNonDirectory   = 0x40
	fileSynchronous    = 0x20
	fileOpenReparse    = 0x200000
	readAttributes     = 0x80
	readDataOrList     = 0x1
	traverse           = 0x20
	synchronize        = 0x100000
)

type ntUnicodeString struct {
	length, maximumLength uint16
	buffer                *uint16
}
type ntObjectAttributes struct {
	length                              uint32
	root                                syscall.Handle
	name                                *ntUnicodeString
	attributes                          uint32
	securityDescriptor, securityQuality uintptr
}
type ntIOStatus struct{ status, information uintptr }
type directory struct {
	file   *os.File
	volume string
}

func nativeAvailable() bool {
	for _, proc := range []*syscall.LazyProc{ntCreateFile, getDriveType, getFinalPath, getVolumeInfo, reOpenFile} {
		if proc.Find() != nil {
			return false
		}
	}
	return true
}

// Relative to an already-held parent. FILE_OPEN never creates/overwrites data.
// Denying share-write/delete prevents conflicting modifications while a handle
// is held; a busy source fails for explicit retry, never a more permissive open.
func openRelative(parent *os.File, name string, isDir bool) (*os.File, error) {
	return openRelativeTyped(parent, name, isDir, !isDir)
}

// Metadata-only enumeration may accept either an ordinary file or directory,
// then classify its confined handle. It never adds data/list access in that mode.
func openRelativeTyped(parent *os.File, name string, isDir, isFile bool) (*os.File, error) {
	if !componentName(name) {
		return nil, Code("source_path_invalid")
	}
	text, err := syscall.UTF16FromString(name)
	if err != nil {
		return nil, Code("source_path_invalid")
	}
	str := ntUnicodeString{uint16((len(text) - 1) * 2), uint16(len(text) * 2), &text[0]}
	attrs := ntObjectAttributes{root: syscall.Handle(parent.Fd()), name: &str,
		attributes: objCaseInsensitive | objDontReparse}
	attrs.length = uint32(unsafe.Sizeof(attrs))
	options := uint32(fileSynchronous | fileOpenReparse)
	if isFile {
		options |= fileNonDirectory
	}
	access := uint32(readAttributes | synchronize)
	if isDir {
		options = fileSynchronous | fileOpenReparse | fileDirectory
		access |= traverse | readDataOrList
	}
	var handle syscall.Handle
	var status ntIOStatus
	result, _, _ := ntCreateFile.Call(uintptr(unsafe.Pointer(&handle)), uintptr(access),
		uintptr(unsafe.Pointer(&attrs)), uintptr(unsafe.Pointer(&status)), 0, 0,
		syscall.FILE_SHARE_READ, fileOpen, uintptr(options), 0, 0)
	runtime.KeepAlive(parent)
	runtime.KeepAlive(text)
	// Accept only synchronous STATUS_SUCCESS/FILE_OPENED, not pending/informational
	// status. Do not expose native diagnostics, names or paths.
	if result != 0 || status.information != 1 {
		if handle != 0 && handle != syscall.InvalidHandle {
			syscall.CloseHandle(handle)
		}
		return nil, Code("source_unavailable")
	}
	return os.NewFile(uintptr(handle), "profile-handle"), nil
}

func volumeID(file *os.File) (string, error) {
	var text [4096]uint16
	// FILE_NAME_OPENED | VOLUME_NAME_GUID: no normalization by name lookup. SMB
	// has no volume GUID; a missing/restricted result is unsupported, not fallback.
	count, _, _ := getFinalPath.Call(file.Fd(), uintptr(unsafe.Pointer(&text[0])), uintptr(len(text)), 0x9)
	runtime.KeepAlive(file)
	if count == 0 || count >= uintptr(len(text)) {
		return "", Code("source_filesystem_unsupported")
	}
	value := syscall.UTF16ToString(text[:count])
	if !strings.HasPrefix(value, `\\?\Volume{`) {
		return "", Code("source_filesystem_unsupported")
	}
	end := strings.Index(value, `}\`)
	if end != 47 {
		return "", Code("source_filesystem_unsupported")
	}
	return strings.ToUpper(value[:end+2]), nil
}

func validateHandle(file *os.File, isDir bool, expectedVolume string) (string, error) {
	handle := syscall.Handle(file.Fd())
	kind, err := syscall.GetFileType(handle)
	if err != nil || kind != syscall.FILE_TYPE_DISK {
		return "", Code("source_unsafe")
	}
	var info syscall.ByHandleFileInformation
	if syscall.GetFileInformationByHandle(handle, &info) != nil {
		return "", Code("source_unavailable")
	}
	// Reparse, device, offline and recall-on-open/data-access placeholders. Do not
	// hydrate files, invoke device semantics or follow even an in-root junction.
	if info.FileAttributes&(0x400|0x40|0x1000|0x40000|0x400000) != 0 ||
		(info.FileAttributes&syscall.FILE_ATTRIBUTE_DIRECTORY != 0) != isDir ||
		(!isDir && info.NumberOfLinks != 1) {
		return "", Code("source_unsafe")
	}
	var filesystem [32]uint16
	ok, _, _ := getVolumeInfo.Call(file.Fd(), 0, 0, 0, 0, 0,
		uintptr(unsafe.Pointer(&filesystem[0])), uintptr(len(filesystem)))
	// NTFS only for this first native implementation: ReFS needs independently
	// qualified 128-bit file identity semantics. Never infer support from DRIVE_FIXED.
	if ok == 0 || syscall.UTF16ToString(filesystem[:]) != "NTFS" {
		return "", Code("source_filesystem_unsupported")
	}
	volume, err := volumeID(file)
	if err != nil {
		return "", err
	}
	if expectedVolume != "" && volume != expectedVolume {
		return "", Code("source_unsafe")
	}
	return volume, nil
}

func openDirectory(ctx context.Context, path string) (*directory, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	drive, parts, ok := windowsRootParts(path)
	if !ok {
		return nil, Code("source_path_invalid")
	}
	if !nativeAvailable() {
		return nil, Code("source_boundary_unavailable")
	}
	wideDrive, _ := syscall.UTF16PtrFromString(drive)
	kind, _, _ := getDriveType.Call(uintptr(unsafe.Pointer(wideDrive)))
	if kind != 3 {
		return nil, Code("source_filesystem_unsupported")
	} // DRIVE_FIXED
	handle, err := syscall.CreateFile(wideDrive, readAttributes|readDataOrList|traverse|synchronize,
		syscall.FILE_SHARE_READ, nil, syscall.OPEN_EXISTING,
		syscall.FILE_FLAG_BACKUP_SEMANTICS|syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return nil, Code("source_unavailable")
	}
	current := os.NewFile(uintptr(handle), "profile-anchor")
	defer func() {
		if current != nil {
			current.Close()
		}
	}()
	volume, err := validateHandle(current, true, "")
	if err != nil {
		return nil, err
	}
	for _, part := range parts {
		if err := check(ctx); err != nil {
			return nil, err
		}
		next, err := openRelative(current, part, true)
		if err != nil {
			return nil, err
		}
		current.Close()
		current = next
		if _, err := validateHandle(current, true, volume); err != nil {
			return nil, err
		}
	}
	if err := check(ctx); err != nil {
		return nil, err
	}
	result := &directory{current, volume}
	current = nil
	return result, nil
}

func (d *directory) close() { d.file.Close() }

func (d *directory) metadata(ctx context.Context, name string) (*os.File, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if !fileName(name) {
		return nil, Code("source_path_invalid")
	}
	if _, err := validateHandle(d.file, true, d.volume); err != nil {
		return nil, err
	}
	file, err := openRelative(d.file, name, false)
	if err != nil {
		return nil, err
	}
	if _, err := validateHandle(file, false, d.volume); err != nil {
		file.Close()
		return nil, err
	}
	if err := check(ctx); err != nil {
		file.Close()
		return nil, err
	}
	return file, nil
}

func (d *directory) open(ctx context.Context, name string) (*os.File, error) {
	metadata, err := d.metadata(ctx, name)
	if err != nil {
		return nil, err
	}
	defer metadata.Close()
	before, err := metadata.Stat()
	if err != nil {
		return nil, Code("source_unavailable")
	}
	// Only an already-validated ordinary inode gets data access. ReOpenFile uses
	// that handle, not the original pathname; the metadata handle remains held.
	handle, _, _ := reOpenFile.Call(metadata.Fd(), readAttributes|readDataOrList|synchronize, syscall.FILE_SHARE_READ,
		syscall.FILE_FLAG_OPEN_REPARSE_POINT|0x100000) // OPEN_NO_RECALL
	runtime.KeepAlive(metadata)
	if handle == 0 || syscall.Handle(handle) == syscall.InvalidHandle {
		return nil, Code("source_unavailable")
	}
	file := os.NewFile(handle, "profile-handle")
	if _, err := validateHandle(file, false, d.volume); err != nil {
		file.Close()
		return nil, err
	}
	if !unchanged(file, before) {
		file.Close()
		return nil, Code("source_changed")
	}
	if err := check(ctx); err != nil {
		file.Close()
		return nil, err
	}
	return file, nil
}

func (d *directory) inspect(ctx context.Context, name string) error {
	file, err := d.metadata(ctx, name)
	if err != nil {
		return err
	}
	file.Close()
	return nil
}

func sameChange(before, after os.FileInfo) bool {
	a, aOK := before.Sys().(*syscall.Win32FileAttributeData)
	b, bOK := after.Sys().(*syscall.Win32FileAttributeData)
	// Windows FileInfo has no Unix ctime; do not claim parity with that check.
	// Held handles deny share-write/delete, with identity/size/mtime checked by
	// unchanged. This is still not an atomic multi-file snapshot.
	return aOK && bOK && a.FileAttributes == b.FileAttributes && a.CreationTime == b.CreationTime
}
