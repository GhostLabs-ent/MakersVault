package presetfiles

import (
	"reflect"
	"strings"
	"testing"
)

func TestWindowsRootSyntax(t *testing.T) {
	for _, path := range []string{`C:\Users\Maker\AppData\Roaming\BambuStudio\system\BBL\machine`, `d:\Profils français\多色`} {
		drive, parts, ok := windowsRootParts(path)
		if !ok || drive != strings.ToUpper(path[:3]) || !reflect.DeepEqual(parts, strings.Split(path[3:], `\`)) {
			t.Fatalf("ordinary path rejected: %q", path)
		}
	}
	for _, path := range []string{"", `C:\`, `C:relative`, `\relative`, `C:/profiles`, `\\server\share\machine`,
		`\\?\C:\machine`, `\\.\C:\machine`, `\??\C:\machine`, `C:\a\..\machine`, `C:\a\.\machine`,
		`C:\a\\machine`, `C:\machine\`, `C:\machine.`, `C:\machine `, `C:\a:stream`, `C:\CON\machine`,
		`C:\COM¹\machine`, "C:\\private\n\\machine", `1:\machine`, `C:\https://host`, "/tmp/machine",
		`C:\` + strings.Repeat("a", 256)} {
		if _, _, ok := windowsRootParts(path); ok {
			t.Errorf("unsafe path accepted: %q", path)
		}
	}
}

func TestUnicodeFilenameFold(t *testing.T) {
	for _, pair := range [][2]string{{"PRINTER.JSON", "printer.json"}, {"Σ.json", "ς.json"}, {"K.json", "k.json"}} {
		if !strings.EqualFold(pair[0], pair[1]) || foldName(pair[0]) != foldName(pair[1]) {
			t.Fatal("simple-fold alias escaped collision check")
		}
	}
	if foldName("a.json") == foldName("b.json") {
		t.Fatal("distinct identities merged")
	}
}

func FuzzWindowsRootSyntax(f *testing.F) {
	for _, name := range []string{`C:\Users\Maker\machine`, `\\server\share`, `C:\a\..\b`, `C:relative`} {
		f.Add(name)
	}
	f.Fuzz(func(t *testing.T, name string) {
		drive, parts, ok := windowsRootParts(name)
		if !ok {
			return
		}
		if len(drive) != 3 || len(parts) == 0 || len(name) > 4096 {
			t.Fatal("invalid accepted root")
		}
		for _, part := range parts {
			if !componentName(part) {
				t.Fatal("invalid component")
			}
		}
	})
}
