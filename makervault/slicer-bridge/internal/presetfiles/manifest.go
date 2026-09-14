package presetfiles

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"strings"
	"unicode/utf8"

	"makersvault/slicer-bridge/internal/printerpreset"
)

// BambuManifest is a LOCAL index, not a list of selectable printers or an API
// import payload. machine_list also contains inheritance and G-code templates.
// No referenced document is opened here. The future adapter must bind each file's
// actual identity to this index; Resolve must prove instantiation, inheritance
// and geometry before offering a preset.
type BambuManifest struct {
	BundleVersion string          `json:"bundle_version"`
	Machines      []ManifestEntry `json:"machines"`
}

type ManifestEntry struct {
	Name string `json:"name"`
	File string `json:"file"` // one basename relative to a separately approved machine root
}

// Validate also checks the private worker response; it confers no filesystem or
// consent authority. A manifest version is never an application version.
func (m BambuManifest) Validate() bool {
	parts := strings.Split(m.BundleVersion, ".")
	if len(parts) != 4 || m.Machines == nil || len(m.Machines) > MaxEntries {
		return false
	}
	for _, part := range parts {
		if len(part) == 0 || len(part) > 5 {
			return false
		}
		for _, r := range part {
			if r < '0' || r > '9' {
				return false
			}
		}
	}
	names, files := map[string]bool{}, map[string]bool{}
	for _, entry := range m.Machines {
		if entry.Name == "" || utf8.RuneCountInString(entry.Name) > 200 || !safeText(entry.Name) ||
			strings.TrimSpace(entry.Name) != entry.Name || !fileName(entry.File) ||
			names[entry.Name] || files[foldName(entry.File)] {
			return false
		}
		names[entry.Name], files[foldName(entry.File)] = true, true
	}
	return true
}

// SelectFiles maps an explicit set of exact manifest identities to basenames.
// It does not guess filenames, auto-select all entries, follow includes, infer
// parent closure, or assert that an entry is an instantiated printer. This is a
// bounded local planning primitive; the final normalized-preset limit is separate.
func (m BambuManifest) SelectFiles(names []string) ([]string, error) {
	if !m.Validate() || len(names) == 0 || len(names) > MaxEntries {
		return nil, Code("manifest_selection_invalid")
	}
	index := make(map[string]string, len(m.Machines))
	for _, entry := range m.Machines {
		index[entry.Name] = entry.File
	}
	files := make([]string, 0, len(names))
	seen := map[string]bool{}
	for _, name := range names {
		file, ok := index[name]
		if !ok || seen[name] {
			return nil, Code("manifest_selection_invalid")
		}
		seen[name] = true
		files = append(files, file)
	}
	return files, nil
}

// ReadBambuManifest reads only the adapter-owned BBL.json basename beneath an
// explicitly locally approved profiles/system root. It neither lists nor visits
// BBL/machine, user accounts, general config, OTA paths or manifest URLs. Production
// callers must use the isolated worker; this function has cooperative cancellation.
func ReadBambuManifest(ctx context.Context, root string) (*BambuManifest, error) {
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
	beforeRoot, err := dir.file.Stat()
	if err != nil {
		return nil, Code("source_unavailable")
	}
	file, err := dir.open(ctx, "BBL.json")
	if err != nil {
		return nil, err
	}
	defer file.Close()
	before, err := file.Stat()
	if err != nil {
		return nil, Code("source_unavailable")
	}
	if before.Size() > printerpreset.MaxFileBytes {
		return nil, Code("manifest_bytes_exceeded")
	}
	data, err := io.ReadAll(io.LimitReader(contextReader{ctx, file}, printerpreset.MaxFileBytes+1))
	if ctxErr := check(ctx); ctxErr != nil {
		return nil, ctxErr
	}
	if err != nil {
		return nil, Code("source_unavailable")
	}
	if !unchanged(file, before) || !unchanged(dir.file, beforeRoot) {
		return nil, Code("source_changed")
	}
	return ParseBambuManifest(ctx, data)
}

// ParseBambuManifest is pure. It retains only the vendor discriminator, bundle
// version and machine_list name/sub_path pairs; every discarded value is still
// checked for duplicate keys, malformed JSON, and structural budgets.
func ParseBambuManifest(ctx context.Context, data []byte) (*BambuManifest, error) {
	ctx, cancel := context.WithTimeout(ctx, printerpreset.MaxDuration)
	defer cancel()
	if err := check(ctx); err != nil {
		return nil, err
	}
	if len(data) > printerpreset.MaxFileBytes {
		return nil, Code("manifest_bytes_exceeded")
	}
	if !utf8.Valid(data) {
		return nil, Code("manifest_invalid")
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	walker := manifestWalker{ctx: ctx, decoder: d}
	value, err := walker.value("root", 0)
	if err != nil {
		return nil, err
	}
	if _, err := d.Token(); err != io.EOF {
		return nil, Code("manifest_invalid")
	}
	fields := value.(map[string]any)
	if fields["name"] != "Bambulab" {
		return nil, Code("manifest_unsupported")
	}
	version, _ := fields["version"].(string)
	entries, ok := fields["machine_list"].([]any)
	if !ok {
		return nil, Code("manifest_invalid")
	}
	manifest := &BambuManifest{BundleVersion: version, Machines: []ManifestEntry{}}
	for _, raw := range entries {
		entry := raw.(map[string]any)
		name, _ := entry["name"].(string)
		subpath, _ := entry["sub_path"].(string)
		if !strings.HasPrefix(subpath, "machine/") {
			return nil, Code("manifest_invalid")
		}
		manifest.Machines = append(manifest.Machines, ManifestEntry{name, strings.TrimPrefix(subpath, "machine/")})
	}
	if !manifest.Validate() {
		return nil, Code("manifest_invalid")
	}
	if err := check(ctx); err != nil {
		return nil, err
	}
	return manifest, nil
}

type manifestWalker struct {
	ctx     context.Context
	decoder *json.Decoder
	nodes   int
}

func (w *manifestWalker) value(mode string, depth int) (any, error) {
	if err := check(w.ctx); err != nil {
		return nil, err
	}
	w.nodes++
	if depth > 16 || w.nodes > 250000 {
		return nil, Code("manifest_structure_limit")
	}
	token, err := w.decoder.Token()
	if err != nil {
		return nil, Code("manifest_invalid")
	}
	delim, container := token.(json.Delim)
	if mode == "text" {
		text, ok := token.(string)
		if !ok || len(text) > 1024 || !safeText(text) {
			return nil, Code("manifest_invalid")
		}
		return text, nil
	}
	if (mode == "root" || mode == "entry") && delim != '{' || mode == "machines" && delim != '[' {
		return nil, Code("manifest_invalid")
	}
	if !container {
		return nil, nil // discarded scalar
	}
	switch delim {
	case '{':
		var out map[string]any
		if mode != "drop" {
			out = map[string]any{}
		}
		seen := map[string]bool{}
		for w.decoder.More() {
			token, err := w.decoder.Token()
			key, ok := token.(string)
			folded := strings.ToLower(key)
			if err != nil || !ok || key == "" || len(key) > 200 || !safeText(key) || seen[folded] {
				return nil, Code("manifest_invalid")
			}
			for _, r := range key {
				if r > 127 {
					return nil, Code("manifest_invalid")
				}
			}
			seen[folded] = true
			if len(seen) > 2048 {
				return nil, Code("manifest_structure_limit")
			}
			if mode == "root" && (folded == "schema_version" || folded == "format_version") {
				return nil, Code("manifest_unsupported")
			}
			next := "drop"
			if mode == "root" && (key == "name" || key == "version") || mode == "entry" && (key == "name" || key == "sub_path") {
				next = "text"
			} else if mode == "root" && key == "machine_list" {
				next = "machines"
			}
			value, err := w.value(next, depth+1)
			if err != nil {
				return nil, err
			}
			if next != "drop" {
				out[key] = value
			}
		}
		if end, err := w.decoder.Token(); err != nil || end != json.Delim('}') {
			return nil, Code("manifest_invalid")
		}
		return out, nil
	case '[':
		var out []any
		if mode == "machines" {
			out = []any{}
		}
		for w.decoder.More() {
			next := "drop"
			if mode == "machines" {
				if len(out) >= MaxEntries {
					return nil, Code("manifest_entry_limit")
				}
				next = "entry"
			}
			value, err := w.value(next, depth+1)
			if err != nil {
				return nil, err
			}
			if next != "drop" {
				out = append(out, value)
			}
		}
		if end, err := w.decoder.Token(); err != nil || end != json.Delim(']') {
			return nil, Code("manifest_invalid")
		}
		return out, nil
	default:
		return nil, Code("manifest_invalid")
	}
}
