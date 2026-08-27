package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

var registeredProtocolSchemes = []string{slicerScheme, engraveScheme, generalScheme}

func macBundleInfoPlist() string {
	var schemes strings.Builder
	for _, scheme := range registeredProtocolSchemes {
		fmt.Fprintf(&schemes, "      <string>%s</string>\n", scheme)
	}
	return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDisplayName</key>
  <string>MakerVault Bridge</string>
  <key>CFBundleExecutable</key>
  <string>makersvault-slicer</string>
  <key>CFBundleIdentifier</key>
  <string>com.makersvault.bridge</string>
  <key>CFBundleName</key>
  <string>MakerVault Bridge</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleURLTypes</key>
  <array>
    <dict>
      <key>CFBundleURLName</key>
      <string>MakerVault local file handoff</string>
      <key>CFBundleURLSchemes</key>
      <array>
` + schemes.String() + `      </array>
    </dict>
  </array>
  <key>LSBackgroundOnly</key>
  <true/>
</dict>
</plist>
`
}

func macBundlePath(home string) string {
	return filepath.Join(home, "Applications", "MakerVault Bridge.app")
}

func darwinApplicationCandidates(candidates []string, home string) []string {
	result := make([]string, 0, len(candidates)*2)
	for _, candidate := range candidates {
		result = append(result, candidate)
		if home != "" && strings.HasPrefix(candidate, "/Applications/") {
			result = append(result, filepath.Join(home, "Applications", strings.TrimPrefix(candidate, "/Applications/")))
		}
	}
	return result
}

func samePath(a, b string) bool {
	if runtime.GOOS == "windows" {
		return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
	}
	return filepath.Clean(a) == filepath.Clean(b)
}

func copyFile(src, dst string, perm os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if perm != 0 {
		if err := os.Chmod(dst, perm); err != nil && runtime.GOOS != "windows" {
			return err
		}
	}
	return nil
}
