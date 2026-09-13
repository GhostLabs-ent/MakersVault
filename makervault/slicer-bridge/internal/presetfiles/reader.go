// Package presetfiles is an internal read-only boundary for locally selected
// profile documents. It is not a browser-facing filesystem or discovery service.
package presetfiles

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"makersvault/slicer-bridge/internal/printerpreset"
)

const MaxEntries = 10000

// Input is supplied ONLY by a future locally consented adapter, never by a
// protocol URL or server payload. Files are exact basenames, not profile names.
// JSON deliberately cannot carry filesystem authority through this type.
type Input struct {
	Root   string               `json:"-"`
	Files  []string             `json:"-"`
	Source printerpreset.Source `json:"-"`
}

type Code string

func (c Code) Error() string { return string(c) }

func check(ctx context.Context) error {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return Code("source_time_budget_exceeded")
	}
	if ctx.Err() != nil {
		return Code("source_cancelled")
	}
	return nil
}

func safeText(value string) bool {
	if !utf8.ValidString(value) {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

// Restrict names to one portable ordinary JSON basename. Windows reserved names
// and ADS syntax are rejected even when listing on Linux; no URL/path expansion.
func fileName(name string) bool {
	if len(name) == 0 || len(name) > 255 || !safeText(name) ||
		strings.ContainsAny(name, `/\:<>"|?*`) || strings.TrimSpace(name) != name ||
		!strings.EqualFold(filepath.Ext(name), ".json") {
		return false
	}
	stem := strings.ToUpper(strings.TrimRight(strings.SplitN(name, ".", 2)[0], " ."))
	if stem == "" || stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" ||
		stem == "CONIN$" || stem == "CONOUT$" {
		return false
	}
	if len(stem) == 4 && (strings.HasPrefix(stem, "COM") || strings.HasPrefix(stem, "LPT")) &&
		stem[3] >= '0' && stem[3] <= '9' {
		return false
	}
	// Windows also reserves the superscript 1/2/3 spellings.
	for _, prefix := range []string{"COM", "LPT"} {
		for _, suffix := range []string{"¹", "²", "³"} {
			if stem == prefix+suffix {
				return false
			}
		}
	}
	return true
}

func rootName(name string) bool {
	return len(name) <= 4096 && safeText(name) && filepath.IsAbs(name) &&
		filepath.Clean(name) == name && name != string(filepath.Separator) &&
		!strings.ContainsAny(name, `\`) && !strings.HasPrefix(name, "//")
}

// ListJSON lists only direct JSON children of an explicitly selected root. It
// never recursively visits directories or reads profile contents. Every entry,
// including ignored non-JSON files, counts toward the directory budget. The
// returned names are local-only, NOT a qualified Bambu manifest or UI selection.
func ListJSON(ctx context.Context, root string) ([]string, error) {
	ctx, cancel := context.WithTimeout(ctx, printerpreset.MaxDuration)
	defer cancel()
	if err := check(ctx); err != nil {
		return nil, err
	}
	if !rootName(root) {
		return nil, Code("source_path_invalid")
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
			if count > MaxEntries {
				return nil, Code("source_entry_limit_exceeded")
			}
			name := entry.Name()
			if !strings.EqualFold(filepath.Ext(name), ".json") {
				continue
			}
			if !fileName(name) {
				return nil, Code("source_path_invalid")
			}
			folded := strings.ToLower(name)
			if seen[folded] {
				return nil, Code("source_ambiguous_filename")
			}
			seen[folded] = true
			// Do not trust d_type or a path-based pre-check; inspect the confined handle.
			if err := dir.inspect(ctx, name); err != nil {
				return nil, err
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

// LoadBambu reads an explicit local file selection, with at most one system and
// one user root in one namespace. No partial catalog escapes on failure. The
// caller still resolves/reviews exact preset identities; this is not manifest
// discovery, application-version detection, or consent to send metadata.
func LoadBambu(ctx context.Context, inputs []Input) (*printerpreset.Catalog, error) {
	// The returned catalog uses the caller context, not the short-lived I/O context.
	// Its own original 15-second budget continues through subsequent resolution.
	catalog := printerpreset.NewBambu(ctx)
	ctx, cancel := context.WithTimeout(ctx, printerpreset.MaxDuration)
	defer cancel()
	return loadBambu(ctx, inputs, catalog)
}

func loadBambu(ctx context.Context, inputs []Input, catalog *printerpreset.Catalog) (*printerpreset.Catalog, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if len(inputs) == 0 || len(inputs) > 2 {
		return nil, Code("source_selection_invalid")
	}
	count := 0
	kinds := map[printerpreset.Kind]bool{}
	for _, input := range inputs {
		if !rootName(input.Root) || len(input.Files) == 0 || kinds[input.Source.Kind] ||
			(input.Source.Kind != printerpreset.System && input.Source.Kind != printerpreset.User) ||
			input.Source.Namespace != inputs[0].Source.Namespace {
			return nil, Code("source_selection_invalid")
		}
		kinds[input.Source.Kind] = true
		seen := map[string]bool{}
		for _, name := range input.Files {
			count++
			if count > printerpreset.MaxFiles {
				return nil, Code("source_file_limit_exceeded")
			}
			if !fileName(name) {
				return nil, Code("source_path_invalid")
			}
			folded := strings.ToLower(name)
			if seen[folded] {
				return nil, Code("source_ambiguous_filename")
			}
			seen[folded] = true
		}
	}
	for _, input := range inputs {
		if err := loadRoot(ctx, input, catalog); err != nil {
			return nil, err
		}
	}
	if err := check(ctx); err != nil {
		return nil, err
	}
	return catalog, nil
}

func loadRoot(ctx context.Context, input Input, catalog *printerpreset.Catalog) error {
	dir, err := openDirectory(ctx, input.Root)
	if err != nil {
		return err
	}
	defer dir.close()
	before, err := dir.file.Stat()
	if err != nil {
		return Code("source_unavailable")
	}
	for _, name := range input.Files {
		if err := loadFile(ctx, dir, name, input.Source, catalog); err != nil {
			return err
		}
	}
	if !unchanged(dir.file, before) {
		return Code("source_changed")
	}
	return check(ctx)
}

func loadFile(ctx context.Context, dir *directory, name string, source printerpreset.Source, catalog *printerpreset.Catalog) error {
	file, err := dir.open(ctx, name)
	if err != nil {
		return err
	}
	defer file.Close()
	before, err := file.Stat()
	if err != nil {
		return Code("source_unavailable")
	}
	if before.Size() > printerpreset.MaxFileBytes {
		return printerpreset.Code("file_bytes_exceeded")
	}
	if err := catalog.Add(source, contextReader{ctx, file}); err != nil {
		if ctxErr := check(ctx); ctxErr != nil {
			return ctxErr
		}
		return err
	}
	if !unchanged(file, before) {
		return Code("source_changed")
	}
	return check(ctx)
}

type contextReader struct {
	ctx  context.Context
	file *os.File
}

func (r contextReader) Read(p []byte) (int, error) {
	if err := check(r.ctx); err != nil {
		return 0, err
	}
	// Cooperative cancellation only. Regular-file kernel I/O can still stall;
	// a process-isolated hard deadline is required before CLI activation.
	return r.file.Read(p)
}

func unchanged(file *os.File, before os.FileInfo) bool {
	after, err := file.Stat()
	return err == nil && os.SameFile(before, after) && before.Mode() == after.Mode() &&
		before.Size() == after.Size() && before.ModTime() == after.ModTime() && sameChange(before, after)
}
