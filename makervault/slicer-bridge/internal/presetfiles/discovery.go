package presetfiles

import (
	"context"
	"strings"
	"unicode/utf8"

	"makersvault/slicer-bridge/internal/printerpreset"
)

const MaxSelected = 100
const discoveryNamespace = "chosen-bambu-location" // never an account or directory

// BambuDiscovery stays local. These are selectable identities with resolved
// parent chains, NOT installed/owned printers or geometry-complete snapshots.
// Hidden machines and excluded script entries are counted, never silently offered.
type BambuDiscovery struct {
	BundleVersion      string                    `json:"bundle_version"`
	ApplicationVersion string                    `json:"application_version"`
	UserIncluded       bool                      `json:"user_included"`
	HiddenMachines     int                       `json:"hidden_machines"`
	ExcludedScripts    int                       `json:"excluded_scripts"`
	Selections         []printerpreset.Selection `json:"selections"`
}

func ValidSelections(picks []printerpreset.Selection, limit int) bool {
	if len(picks) > limit {
		return false
	}
	seen := map[printerpreset.Selection]bool{}
	for _, pick := range picks {
		if (pick.Kind != printerpreset.System && pick.Kind != printerpreset.User) ||
			pick.Name == "" || !safeText(pick.Name) || utf8.RuneCountInString(pick.Name) > 200 ||
			strings.TrimSpace(pick.Name) != pick.Name || seen[pick] {
			return false
		}
		seen[pick] = true
	}
	return true
}

func (d BambuDiscovery) Validate(userIncluded bool) bool {
	manifest := BambuManifest{BundleVersion: d.BundleVersion, Machines: []ManifestEntry{}}
	if !manifest.Validate() || d.ApplicationVersion != "" || d.UserIncluded != userIncluded ||
		d.Selections == nil || d.HiddenMachines < 0 || d.ExcludedScripts < 0 ||
		d.HiddenMachines > MaxEntries || d.ExcludedScripts > MaxEntries ||
		d.HiddenMachines+d.ExcludedScripts+len(d.Selections) >= MaxEntries ||
		!ValidSelections(d.Selections, MaxEntries-1) {
		return false
	}
	for i, pick := range d.Selections {
		if (!userIncluded && pick.Kind == printerpreset.User) || printerpreset.IsBambuScriptTemplate(pick.Name) {
			return false
		}
		if i > 0 {
			previous := d.Selections[i-1]
			if previous.Kind > pick.Kind || (previous.Kind == pick.Kind && previous.Name >= pick.Name) {
				return false
			}
		}
	}
	return true
}

// DiscoverBambu reads one explicit location. No general settings, account guess,
// include target, unlisted system file, URL or app executable is opened. Production
// must call through the isolated worker after local consent; direct I/O cooperates.
func DiscoverBambu(ctx context.Context, root, account string) (*BambuDiscovery, error) {
	discovery, _, err := scanBambu(ctx, root, account, nil)
	return discovery, err
}

// SelectBambu revalidates the current full bounded index before projecting an
// exact local selection. It does not trust a previous discovery as a snapshot.
func SelectBambu(ctx context.Context, root, account string, picks []printerpreset.Selection) ([]printerpreset.Candidate, error) {
	if len(picks) == 0 || !ValidSelections(picks, MaxSelected) {
		return nil, Code("source_selection_invalid")
	}
	_, candidates, err := scanBambu(ctx, root, account, picks)
	return candidates, err
}

func scanBambu(ctx context.Context, root, account string, picks []printerpreset.Selection) (*BambuDiscovery, []printerpreset.Candidate, error) {
	ctx, cancel := context.WithTimeout(ctx, printerpreset.MaxDuration)
	defer cancel()
	catalog := printerpreset.NewBambu(ctx)
	session, err := openBambuLocation(ctx, root, account, catalog)
	if err != nil {
		return nil, nil, err
	}
	defer session.close()
	manifest := session.inspection.Manifest
	result := &BambuDiscovery{BundleVersion: manifest.BundleVersion, UserIncluded: account != ""}
	source := printerpreset.Source{Namespace: discoveryNamespace, Kind: printerpreset.System, BundleVersion: manifest.BundleVersion}
	machines := 0
	for _, entry := range manifest.Machines {
		if printerpreset.IsBambuScriptTemplate(entry.Name) {
			result.ExcludedScripts++
			continue
		}
		if err := loadBoundFile(ctx, session.systemMachine, entry.File, entry.Name, source, catalog); err != nil {
			return nil, nil, err
		}
		machines++
	}
	source.Kind = printerpreset.User
	for _, file := range session.inspection.UserFiles {
		if err := loadSavedUserFile(ctx, session.userMachine, file, source, catalog); err != nil {
			return nil, nil, err
		}
		machines++
	}
	result.Selections, err = catalog.Selections(discoveryNamespace)
	if err != nil {
		return nil, nil, err
	}
	result.HiddenMachines = machines - len(result.Selections)
	if !result.Validate(account != "") {
		return nil, nil, Code("source_selection_invalid")
	}
	candidates := []printerpreset.Candidate{}
	for _, pick := range picks {
		candidate, err := catalog.Resolve(discoveryNamespace, pick.Kind, pick.Name)
		if err != nil {
			return nil, nil, err
		}
		candidates = append(candidates, candidate)
	}
	if err := session.check(ctx); err != nil {
		return nil, nil, err
	}
	return result, candidates, nil
}
