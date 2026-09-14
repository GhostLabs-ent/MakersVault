package presetworker

import (
	"context"
	"runtime"
	"strings"

	"makersvault/slicer-bridge/internal/presetfiles"
)

// NativeLocations is for a locally consented caller, never public JSON input.
// Windows Shell lookup runs inside the existing hard-deadline/reap-slot worker.
// Linux's provider only copies two environment strings and runs the pure planner:
// no native filesystem/NSS call, worker environment inheritance or path probing.
// Production main still has no worker dispatch or preset-consent caller.
func NativeLocations(ctx context.Context) ([]presetfiles.BambuLocation, error) {
	if runtime.GOOS == "linux" {
		return presetfiles.NativeBambuLocations(ctx)
	}
	if runtime.GOOS != "windows" {
		return nil, Code("source_platform_unsupported")
	}
	result, err := Run(ctx, Request{Operation: "native-locations"})
	return result.Locations, err
}

// The Windows operation has exactly one known-root plan, never custom/arbitrary
// roots or mixed channels. Validate it again in the parent before local display.
func validNativeLocations(locations []wireLocation) bool {
	if len(locations) != 3 {
		return false
	}
	base := strings.TrimSuffix(locations[0].DataRoot, `\BambuStudio`)
	if base == locations[0].DataRoot {
		return false
	}
	plan, err := presetfiles.PlanBambuLocations(presetfiles.LocationHints{Platform: "windows", RoamingAppData: base})
	if err != nil {
		return false
	}
	for i, location := range plan {
		if locations[i].ID != location.ID || locations[i].DataRoot != location.DataRoot {
			return false
		}
	}
	return true
}
