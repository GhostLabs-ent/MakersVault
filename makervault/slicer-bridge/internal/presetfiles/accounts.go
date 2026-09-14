package presetfiles

import (
	"context"
	"io"
	"runtime"
	"sort"

	"makersvault/slicer-bridge/internal/printerpreset"
)

// AccountChoices is LOCAL-ONLY picker data, never a candidate/import payload.
// A name denotes a directory, not an authenticated account or usable presets.
// There is deliberately no selected/default/active account field.
type AccountChoices struct {
	Names []string `json:"names"`
}

func (v AccountChoices) Validate() bool {
	if v.Names == nil || len(v.Names) > MaxEntries {
		return false
	}
	seen := map[string]bool{}
	for i, name := range v.Names {
		if !componentName(name) || seen[foldName(name)] || (i > 0 && name <= v.Names[i-1]) {
			return false
		}
		seen[foldName(name)] = true
	}
	return true
}

// ListBambuAccounts inspects only direct entries in chosen-root/user. It does
// not descend into accounts or require/read a system manifest. Missing user is
// an explicit error, not a successful empty listing or an automatic system-only
// choice. Call only through the isolated worker after future local consent.
func ListBambuAccounts(ctx context.Context, root string) (*AccountChoices, error) {
	ctx, cancel := context.WithTimeout(ctx, printerpreset.MaxDuration)
	defer cancel()
	if err := check(ctx); err != nil {
		return nil, err
	}
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		return nil, Code("source_platform_unsupported")
	}
	dir, err := openDirectory(ctx, root)
	if err != nil {
		return nil, err
	}
	defer dir.close()
	before, err := dir.file.Stat()
	if err != nil {
		return nil, Code("source_unavailable")
	}
	user, err := dir.child(ctx, "user")
	if err != nil {
		return nil, err
	}
	defer user.close()
	names, err := listAccounts(ctx, user, MaxEntries)
	if err != nil {
		return nil, err
	}
	if !unchanged(dir.file, before) {
		return nil, Code("source_changed")
	}
	if err := check(ctx); err != nil {
		return nil, err
	}
	return &AccountChoices{Names: names}, nil
}

func listAccounts(ctx context.Context, dir *directory, allowance int) ([]string, error) {
	before, err := dir.file.Stat()
	if err != nil {
		return nil, Code("source_unavailable")
	}
	names := []string{}
	seen := map[string]bool{}
	count := 0
	for {
		if err := check(ctx); err != nil {
			return nil, err
		}
		entries, readErr := dir.file.ReadDir(64)
		for _, entry := range entries {
			count++
			if count > allowance {
				return nil, Code("source_entry_limit_exceeded")
			}
			name := entry.Name()
			if !componentName(name) {
				return nil, Code("source_path_invalid")
			}
			if seen[foldName(name)] {
				return nil, Code("source_ambiguous_filename")
			}
			seen[foldName(name)] = true
			// Never trust d_type/IsDir or open a profile body to classify an entry.
			isDirectory, err := dir.accountEntry(ctx, name)
			if err != nil {
				return nil, err
			}
			if !isDirectory {
				continue // ordinary single-link sidecars count but are not choices
			}
			names = append(names, name)
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return nil, Code("source_unavailable")
		}
	}
	if !unchanged(dir.file, before) {
		return nil, Code("source_changed")
	}
	if err := check(ctx); err != nil {
		return nil, err
	}
	sort.Strings(names)
	return names, nil
}
