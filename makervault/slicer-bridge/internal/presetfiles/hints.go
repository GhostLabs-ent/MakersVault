package presetfiles

import "context"

// NativeBambuLocations acquires current-user hints on the LOCAL workstation,
// without testing candidate existence or selecting an installation. This is not
// called by production main. The consent foundation calls presetworker.NativeLocations:
// Windows runs this low-level provider only inside the isolated worker; Linux only
// copies environment strings and plans. Never fill hints from browser/server data.
// This direct API remains cooperative and is not an isolated hard-deadline API.
func NativeBambuLocations(ctx context.Context) ([]BambuLocation, error) {
	return nativeBambuLocations(ctx, nativeLocationHints)
}

func nativeBambuLocations(ctx context.Context, acquire func(context.Context) (LocationHints, error)) ([]BambuLocation, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	hints, err := acquire(ctx)
	if contextErr := check(ctx); contextErr != nil {
		return nil, contextErr
	}
	if err != nil {
		// Native diagnostics may include private paths; only fixed codes escape.
		if err == Code("source_platform_unsupported") {
			return nil, err
		}
		return nil, Code("source_hint_unavailable")
	}
	return PlanBambuLocations(hints)
}
