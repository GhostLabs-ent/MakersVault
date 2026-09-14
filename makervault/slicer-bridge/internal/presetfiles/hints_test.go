package presetfiles

import (
	"context"
	"errors"
	"runtime"
	"testing"
)

func TestNativeHintsRemainUnobservedAndRedacted(t *testing.T) {
	for _, hints := range []LocationHints{
		{Platform: "linux", ConfigHome: "/synthetic/nonexistent-config"},
		{Platform: "windows", RoamingAppData: `C:\synthetic\nonexistent-roaming`},
	} {
		calls := 0
		choices, err := nativeBambuLocations(context.Background(), func(context.Context) (LocationHints, error) {
			calls++
			return hints, nil
		})
		if err != nil || len(choices) != 3 || calls != 1 {
			t.Fatal("native hint was treated as installation presence")
		}
	}
	for _, err := range []error{errors.New("PRIVATE_PATH_AND_NATIVE_DIAGNOSTIC"), Code("source_platform_unsupported")} {
		result, got := nativeBambuLocations(context.Background(), func(context.Context) (LocationHints, error) {
			return LocationHints{Platform: "linux", UserHome: "/must-not-fallback"}, err
		})
		want := Code("source_hint_unavailable")
		if err == Code("source_platform_unsupported") {
			want = Code("source_platform_unsupported")
		}
		if result != nil || got != want {
			t.Fatal("native diagnostics leaked or fallback proceeded")
		}
	}
	for _, hints := range []LocationHints{
		{Platform: "windows", RoamingAppData: `\\server\share\private`},
		{Platform: "windows", RoamingAppData: `%APPDATA%`},
		{Platform: "linux", ConfigHome: "relative", UserHome: "/must-not-fallback"},
	} {
		if result, err := nativeBambuLocations(context.Background(), func(context.Context) (LocationHints, error) { return hints, nil }); result != nil || err != Code("source_path_invalid") {
			t.Fatal("invalid hint fell back or was expanded")
		}
	}
}

func TestNativeHintCancellation(t *testing.T) {
	for _, early := range []bool{true, false} {
		ctx, cancel := context.WithCancel(context.Background())
		calls := 0
		if early {
			cancel()
		}
		result, err := nativeBambuLocations(ctx, func(context.Context) (LocationHints, error) {
			calls++
			cancel()
			return LocationHints{Platform: "linux", ConfigHome: "/synthetic"}, nil
		})
		cancel()
		if result != nil || err != Code("source_cancelled") || (early && calls != 0) || (!early && calls != 1) {
			t.Fatal("hint cancellation failed")
		}
	}
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		if result, err := NativeBambuLocations(context.Background()); result != nil || err != Code("source_platform_unsupported") {
			t.Fatal("deferred native hints enabled")
		}
	}
}
