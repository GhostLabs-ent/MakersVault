package presetfiles

import "context"

// NativeBambuLocations acquires current-user hints on the LOCAL workstation,
// without testing candidate existence or selecting an installation. This is not
// called by production main or by the sanitized worker. A future local consent
// flow must call it before constructing private worker requests, never fill hints
// from browser/server data. OS hint acquisition itself is cooperative, not an
// isolated hard-deadline operation; integration must account for that separately.
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
