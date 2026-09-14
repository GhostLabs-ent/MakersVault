//go:build (!windows && !linux) || (!amd64 && !arm64)

package presetui

func nativeAction(request) (string, error) { return "", Code("ui_platform_unsupported") }
