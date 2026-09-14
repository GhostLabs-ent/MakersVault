package presetfiles

import (
	"context"
	"os"
	"path"
	"runtime"
	"strings"

	"makersvault/slicer-bridge/internal/printerpreset"
)

// LocationHints are supplied by a future LOCAL consent flow. This pure planner
// does not read environment variables, find executables, scan a home directory or
// infer which installation/account is active. JSON cannot carry path authority.
type LocationHints struct {
	Platform       string `json:"-"`
	RoamingAppData string `json:"-"`
	ConfigHome     string `json:"-"`
	UserHome       string `json:"-"`
	CustomDataRoot string `json:"-"`
}

type BambuLocation struct {
	ID       string `json:"-"` // local choice label, not an installed build/channel claim
	DataRoot string `json:"-"`
}

func locationRoot(platform, root string) bool {
	if platform == "windows" {
		_, _, ok := windowsRootParts(root)
		return ok
	}
	return platform == "linux" && len(root) <= 4096 && safeText(root) &&
		strings.HasPrefix(root, "/") && root != "/" && path.Clean(root) == root &&
		!strings.Contains(root, `\`)
}

// PlanBambuLocations returns unobserved candidates, never silently choosing one.
// An explicit custom data root REPLACES the known-location plan; bad hints do not
// trigger fallback scans. Packaging-specific roots require explicit local choice.
func PlanBambuLocations(hints LocationHints) ([]BambuLocation, error) {
	if hints.Platform != "windows" && hints.Platform != "linux" {
		return nil, Code("source_platform_unsupported")
	}
	if hints.CustomDataRoot != "" {
		if !locationRoot(hints.Platform, hints.CustomDataRoot) {
			return nil, Code("source_path_invalid")
		}
		return []BambuLocation{{ID: "custom", DataRoot: hints.CustomDataRoot}}, nil
	}
	base, separator := hints.RoamingAppData, `\`
	if hints.Platform == "linux" {
		base, separator = hints.ConfigHome, "/"
		if base == "" {
			if !locationRoot("linux", hints.UserHome) {
				return nil, Code("source_path_invalid")
			}
			base = hints.UserHome + "/.config"
		}
	}
	if !locationRoot(hints.Platform, base) {
		return nil, Code("source_path_invalid")
	}
	choices := []BambuLocation{}
	for _, suffix := range []string{"", "Beta", "Internal"} {
		root := base + separator + "BambuStudio" + suffix
		if !locationRoot(hints.Platform, root) {
			return nil, Code("source_path_invalid")
		}
		choices = append(choices, BambuLocation{ID: "BambuStudio" + suffix, DataRoot: root})
	}
	return choices, nil
}

// LocationInspection remains local-only. UserFiles is a filename index, NOT a
// parsed/selected preset list. The account name and root never enter the result.
// Empty app version deliberately means unobserved, not the manifest's version.
type LocationInspection struct {
	Manifest           BambuManifest `json:"manifest"`
	UserIncluded       bool          `json:"user_included"`
	UserFiles          []string      `json:"user_files"`
	ApplicationVersion string        `json:"application_version"`
}

func (v LocationInspection) Validate(userIncluded bool) bool {
	if !v.Manifest.Validate() || v.UserIncluded != userIncluded || v.ApplicationVersion != "" ||
		v.UserFiles == nil || (!userIncluded && len(v.UserFiles) != 0) ||
		len(v.Manifest.Machines)+len(v.UserFiles) > MaxEntries {
		return false
	}
	seen := map[string]bool{}
	for i, name := range v.UserFiles {
		if !fileName(name) || seen[foldName(name)] || (i > 0 && name <= v.UserFiles[i-1]) {
			return false
		}
		seen[foldName(name)] = true
	}
	return true
}

// InspectBambuLocation reads one explicitly chosen data root, fixed system/BBL
// manifest layout and (only if selected) user/<account>/machine filenames. Empty
// account means system-only, never "default" or guessed cloud account. A caller
// must obtain local consent before invoking this through the isolated worker.
func InspectBambuLocation(ctx context.Context, root, account string) (*LocationInspection, error) {
	ctx, cancel := context.WithTimeout(ctx, printerpreset.MaxDuration)
	defer cancel()
	session, err := openBambuLocation(ctx, root, account, nil)
	if err != nil {
		return nil, err
	}
	defer session.close()
	if err := session.check(ctx); err != nil {
		return nil, err
	}
	return session.inspection, nil
}

// One held ancestry and deadline for inspection AND subsequent document reads.
type bambuLocationSession struct {
	dirs                       []*directory
	before                     []os.FileInfo
	systemMachine, userMachine *directory
	inspection                 *LocationInspection
}

func (s *bambuLocationSession) close() {
	for i := len(s.dirs) - 1; i >= 0; i-- {
		s.dirs[i].close()
	}
}

func (s *bambuLocationSession) check(ctx context.Context) error {
	for i, held := range s.dirs {
		if !unchanged(held.file, s.before[i]) {
			return Code("source_changed")
		}
	}
	return check(ctx)
}

func openBambuLocation(ctx context.Context, root, account string, catalog *printerpreset.Catalog) (result *bambuLocationSession, err error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		return nil, Code("source_platform_unsupported")
	}
	if !rootName(root) || (account != "" && !componentName(account)) {
		return nil, Code("source_path_invalid")
	}
	dir, err := openDirectory(ctx, root)
	if err != nil {
		return nil, err
	}
	// Keep every ancestor held and compare all directory observations before
	// publication. Never derive absolute child paths and reopen them as new roots.
	session := &bambuLocationSession{dirs: []*directory{dir}}
	defer func() {
		if err != nil {
			session.close()
		}
	}()
	stat, err := dir.file.Stat()
	if err != nil {
		return nil, Code("source_unavailable")
	}
	session.before = append(session.before, stat)
	child := func(parent *directory, name string) (*directory, error) {
		next, err := parent.child(ctx, name)
		if err != nil {
			return nil, err
		}
		session.dirs = append(session.dirs, next)
		stat, err := next.file.Stat()
		if err != nil {
			return nil, Code("source_unavailable")
		}
		session.before = append(session.before, stat)
		return next, nil
	}
	system, err := child(dir, "system")
	if err != nil {
		return nil, err
	}
	manifest, err := readBambuManifestBudget(ctx, system, catalog)
	if err != nil {
		return nil, err
	}
	vendor, err := child(system, "BBL")
	if err != nil {
		return nil, err
	}
	session.systemMachine, err = child(vendor, "machine")
	if err != nil {
		return nil, err
	}
	session.inspection = &LocationInspection{Manifest: *manifest, UserIncluded: account != "", UserFiles: []string{}}
	allowance := MaxEntries - len(manifest.Machines)
	// The content scan also charges the fixed manifest itself. Inspection-only
	// retains its existing index-entry contract, since it opens no profile bodies.
	if catalog != nil {
		allowance--
		if allowance < 0 {
			return nil, Code("source_entry_limit_exceeded")
		}
	}
	if account != "" {
		current := dir
		for _, name := range []string{"user", account, "machine"} {
			current, err = child(current, name)
			if err != nil {
				return nil, err
			}
		}
		session.userMachine = current
		session.inspection.UserFiles, err = listJSON(ctx, current, allowance)
		if err != nil {
			return nil, err
		}
	}
	if err := session.check(ctx); err != nil {
		return nil, err
	}
	return session, nil
}
