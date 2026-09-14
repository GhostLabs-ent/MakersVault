// Package printerpreset projects untrusted slicer documents into bounded layout
// metadata. It has no filesystem, network, command, or persistence authority.
package printerpreset

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	ParserVersion       = "bambu-projection-3"
	MaxFiles            = 10000
	MaxFileBytes        = 8 << 20
	MaxTotalBytes       = 128 << 20
	MaxInheritanceDepth = 16
	MaxDuration         = 15 * time.Second
)

// Code is deliberately free of source values, local paths and decoder errors.
type Code string

func (c Code) Error() string { return string(c) }

type Kind string

const (
	System Kind = "system"
	User   Kind = "user"
)

// Source describes one caller-approved namespace. Namespace is local-only: never
// serialize a directory/account name as source identity. Versions may be unknown.
type Source struct {
	Namespace          string
	Kind               Kind
	ApplicationVersion string
	BundleVersion      string
}

type Identity struct {
	Name               string `json:"name"`
	Model              string `json:"model"`
	Variant            string `json:"variant"`
	Kind               Kind   `json:"kind"`
	ApplicationVersion string `json:"application_version"`
	BundleVersion      string `json:"bundle_version"`
}

type Point struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
}

type Provenance struct {
	Bed        string `json:"bed"`
	Exclusions string `json:"exclusions"`
	Height     string `json:"height"`
	Nozzle     string `json:"nozzle"`
}

// Candidate is a review projection, not a stored snapshot or print-ready claim.
// Null exclusions mean unknown; an empty array means explicitly no exclusions.
type Candidate struct {
	SchemaVersion int        `json:"schema_version"`
	AdapterID     string     `json:"adapter_id"`
	ParserVersion string     `json:"parser_version"`
	Source        Identity   `json:"source"`
	Technology    string     `json:"technology"`
	Bed           []Point    `json:"bed_polygon_mm"`
	Exclusions    [][]Point  `json:"exclusion_polygons_mm"`
	Height        *float64   `json:"max_height_mm"`
	Nozzle        *float64   `json:"nozzle_diameter_mm"`
	SourceOrigin  *Point     `json:"source_origin_mm"`
	Provenance    Provenance `json:"provenance"`
	Reasons       []Code     `json:"reasons"`
	Fingerprint   string     `json:"normalized_sha256,omitempty"`
}

func (c Candidate) Complete() bool {
	return c.SchemaVersion == 1 && c.AdapterID == "bambu" && c.Technology == "fdm" &&
		len(c.Bed) >= 3 && c.SourceOrigin != nil && c.Exclusions != nil && c.Height != nil &&
		c.Nozzle != nil && len(c.Fingerprint) == 64 && len(c.Reasons) == 0
}

type key struct {
	namespace string
	kind      Kind
	name      string
}
type document struct {
	source     Source
	fields     map[string]any
	selectable bool // established from explicit headers or the dedicated local-user contract
}
type value struct {
	raw   any
	owner key
}

// Catalog is a single bounded, serial construction/resolution operation. Feed
// already-authorized documents; OS discovery and consent are separate gates.
// Cancellation is cooperative; the caller must make its Reader's I/O cancellable.
type Catalog struct {
	ctx       context.Context
	started   time.Time
	documents map[key]document
	files     int
	bytes     int64
	failed    bool
}

func NewBambu(ctx context.Context) *Catalog {
	return &Catalog{ctx: ctx, started: time.Now(), documents: map[key]document{}}
}

func (c *Catalog) check() error {
	if c.ctx.Err() != nil {
		return Code("cancelled")
	}
	if time.Since(c.started) >= MaxDuration {
		return Code("time_budget_exceeded")
	}
	if c.failed {
		return Code("catalog_incomplete")
	}
	return nil
}

type checkedReader struct {
	catalog *Catalog
	reader  io.Reader
}

func (r checkedReader) Read(p []byte) (int, error) {
	if err := r.catalog.check(); err != nil {
		return 0, err
	}
	return r.reader.Read(p)
}

// Add retains allowlisted fields only. Any failed Add invalidates the catalog,
// preventing resolution from a silently truncated or ambiguous scan.
func (c *Catalog) Add(source Source, reader io.Reader) (err error) {
	return c.add(source, "", reader, false)
}

// AddIndexed binds a system manifest identity to the actual document, never to
// its filename. A mismatch poisons the same catalog as any other failed Add.
func (c *Catalog) AddIndexed(source Source, expected string, reader io.Reader) error {
	if source.Kind != System || !label(expected, false) {
		c.failed = true
		return Code("invalid_source")
	}
	return c.add(source, expected, reader, false)
}

func (c *Catalog) add(source Source, expected string, reader io.Reader, localUserMachine bool) (err error) {
	defer func() {
		if err != nil {
			c.failed = true
		}
	}()
	if err = c.check(); err != nil {
		return err
	}
	if !label(source.Namespace, false) || (source.Kind != System && source.Kind != User) ||
		!label(source.ApplicationVersion, true) || !label(source.BundleVersion, true) {
		return Code("invalid_source")
	}
	data, err := c.read(reader)
	if err != nil {
		return err
	}
	fields, err := c.project(data, localUserMachine)
	if err != nil {
		return err
	}
	for _, marker := range []string{"schema_version", "format_version"} {
		if _, exists := fields[marker]; exists {
			return Code("unsupported_source_schema")
		}
	}
	name, ok := fields["name"].(string)
	if !ok || !label(name, false) {
		return Code("invalid_machine_identity")
	}
	if localUserMachine {
		if err := validateLocalUserMachine(fields); err != nil {
			return err
		}
	} else if fields["type"] != "machine" {
		return Code("invalid_machine_identity")
	}
	if expected != "" && name != expected {
		return Code("manifest_identity_mismatch")
	}
	if from, exists := fields["from"]; exists {
		text, ok := from.(string)
		if !ok || strings.ToLower(text) != string(source.Kind) {
			return Code("source_kind_mismatch")
		}
	}
	for _, field := range []string{"inherits", "printer_model", "printer_variant"} {
		if raw, exists := fields[field]; exists {
			text, ok := raw.(string)
			if !ok || !label(text, true) {
				return Code("invalid_identity_field")
			}
		}
	}
	if raw, exists := fields["instantiation"]; exists && raw != "true" && raw != true && raw != "false" && raw != false {
		return Code("invalid_instantiation")
	}
	id := key{source.Namespace, source.Kind, name}
	if _, exists := c.documents[id]; exists {
		return Code("ambiguous_identity")
	}
	instantiation, explicit := fields["instantiation"]
	selectable := instantiation == "true" || instantiation == true || (localUserMachine && !explicit)
	// Document version identifies saved source bytes, not an observed installation
	// or the system bundle. It is validated locally, never inherited or exported.
	delete(fields, "version")
	c.documents[id] = document{source: source, fields: fields, selectable: selectable}
	return c.check()
}

// ReadIndex charges one adapter-owned index to this SAME file/byte/time budget.
// It grants no file authority and retains no raw text; the caller must validate
// the returned index and abort the entire scan on failure. A read failure latches.
func (c *Catalog) ReadIndex(reader io.Reader) (data []byte, err error) {
	defer func() {
		if err != nil {
			c.failed = true
		}
	}()
	return c.read(reader)
}

func (c *Catalog) read(reader io.Reader) ([]byte, error) {
	if err := c.check(); err != nil {
		return nil, err
	}
	c.files++
	if c.files > MaxFiles {
		return nil, Code("file_count_exceeded")
	}
	remaining := int64(MaxTotalBytes) - c.bytes
	limit := min(int64(MaxFileBytes), remaining)
	data, readErr := io.ReadAll(io.LimitReader(checkedReader{c, reader}, limit+1))
	c.bytes += int64(len(data))
	if readErr != nil {
		if err := c.check(); err != nil {
			return nil, err
		}
		return nil, Code("read_failed")
	}
	if c.bytes > MaxTotalBytes {
		return nil, Code("total_bytes_exceeded")
	}
	if len(data) > MaxFileBytes {
		return nil, Code("file_bytes_exceeded")
	}
	if err := c.check(); err != nil {
		return nil, err
	}
	return data, nil
}

func label(text string, empty bool) bool {
	if !utf8.ValidString(text) || utf8.RuneCountInString(text) > 200 || (!empty && text == "") {
		return false
	}
	for _, r := range text {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

func (c *Catalog) resolve(id key, path map[key]bool, depth int) (map[string]value, error) {
	if err := c.check(); err != nil {
		return nil, err
	}
	if depth > MaxInheritanceDepth {
		return nil, Code("inheritance_depth_exceeded")
	}
	if path[id] {
		return nil, Code("inheritance_cycle")
	}
	doc, exists := c.documents[id]
	if !exists {
		return nil, Code("missing_parent")
	}
	path[id] = true
	defer delete(path, id)
	fields := map[string]value{}
	if parent, _ := doc.fields["inherits"].(string); parent != "" {
		parentID := key{id.namespace, System, parent}
		if id.kind == User {
			userID := key{id.namespace, User, parent}
			_, userExists := c.documents[userID]
			_, systemExists := c.documents[parentID]
			if userExists && systemExists {
				return nil, Code("ambiguous_parent")
			}
			if userExists {
				parentID = userID
			}
		}
		inherited, err := c.resolve(parentID, path, depth+1)
		if err != nil {
			return nil, err
		}
		fields = inherited
	}
	// Unsupported includes anywhere in the chain are not made safe by a child.
	if includes, exists := doc.fields["include"]; exists && !scriptIncludesOnly(includes) {
		return nil, Code("unsupported_include")
	}
	for field, raw := range doc.fields {
		fields[field] = value{raw, id}
	}
	return fields, nil
}

func scriptIncludesOnly(raw any) bool {
	items, ok := raw.([]any)
	if !ok || len(items) > 16 {
		return false
	}
	for _, item := range items {
		name, ok := item.(string)
		if !ok || !IsBambuScriptTemplate(name) {
			return false
		}
	}
	return true
}

// IsBambuScriptTemplate is a conservative EXCLUSION rule, never permission to
// open the named include. Such manifest entries cannot supply layout inheritance.
func IsBambuScriptTemplate(name string) bool {
	if !label(name, false) || strings.ContainsAny(name, `/\`) {
		return false
	}
	for _, suffix := range []string{"machine_start_gcode", "machine_end_gcode", "time_lapse_gcode", "change_filament_gcode", "layer_change_gcode"} {
		if strings.HasSuffix(name, " template "+suffix) {
			return true
		}
	}
	return false
}

// Selection is an exact local identity, not a path or evidence of printer ownership.
type Selection struct {
	Kind Kind   `json:"kind"`
	Name string `json:"name"`
}

// Selections validates EVERY loaded parent chain, including hidden machines,
// before returning deterministic selectable choices. Geometry is
// resolved only for the later bounded selection; choices are not complete presets.
func (c *Catalog) Selections(namespace string) ([]Selection, error) {
	if err := c.check(); err != nil {
		return nil, err
	}
	ids := []key{}
	for id := range c.documents {
		if id.namespace == namespace {
			ids = append(ids, id)
		}
	}
	sort.Slice(ids, func(i, j int) bool {
		if ids[i].kind != ids[j].kind {
			return ids[i].kind < ids[j].kind
		}
		return ids[i].name < ids[j].name
	})
	result := []Selection{}
	for _, id := range ids {
		if _, err := c.resolve(id, map[key]bool{}, 1); err != nil {
			return nil, err
		}
		if c.documents[id].selectable {
			result = append(result, Selection{Kind: id.kind, Name: id.name})
		}
	}
	if err := c.check(); err != nil {
		return nil, err
	}
	return result, nil
}

func (c *Catalog) Resolve(namespace string, kind Kind, name string) (Candidate, error) {
	id := key{namespace, kind, name}
	if err := c.check(); err != nil {
		return Candidate{}, err
	}
	doc, ok := c.documents[id]
	if !ok {
		return Candidate{}, Code("preset_not_found")
	}
	// Only the dedicated machine-directory reader may establish saved-user
	// selectability without a system-style instantiation header.
	if !doc.selectable {
		return Candidate{}, Code("not_selectable")
	}
	fields, err := c.resolve(id, map[key]bool{}, 1)
	if err != nil {
		return Candidate{}, err
	}
	result := Candidate{SchemaVersion: 1, AdapterID: "bambu", ParserVersion: ParserVersion,
		Source: Identity{Name: name, Kind: kind, ApplicationVersion: doc.source.ApplicationVersion,
			BundleVersion: doc.source.BundleVersion}, Reasons: []Code{},
		Provenance: Provenance{"unknown", "unknown", "unknown", "unknown"}, Technology: "unknown"}
	result.Source.Model, _ = fields["printer_model"].raw.(string)
	result.Source.Variant, _ = fields["printer_variant"].raw.(string)
	if fields["printer_technology"].raw == "FFF" {
		result.Technology = "fdm"
	} else {
		result.Reasons = append(result.Reasons, "unsupported_technology")
	}
	structure, _ := fields["printer_structure"].raw.(string)
	if structure != "corexy" && structure != "i3" && structure != "delta" {
		result.Reasons = append(result.Reasons, "unsupported_structure")
	}
	for _, field := range []string{"extruder_printable_area", "extruder_printable_height"} {
		if v, exists := fields[field]; exists {
			items, ok := v.raw.([]any)
			if !ok || len(items) != 0 {
				result.Reasons = append(result.Reasons, "unsupported_tool_geometry")
			}
		}
	}
	for _, field := range []string{"printer_extruder_id", "physical_extruder_map"} {
		if v, exists := fields[field]; exists && !singleTool(v.raw) {
			result.Reasons = append(result.Reasons, "unsupported_multiple_tools")
		}
	}
	for _, field := range []string{"head_wrap_detect_zone", "wrapping_exclude_area"} {
		if v, exists := fields[field]; exists {
			items, ok := v.raw.([]any)
			if !ok || len(items) != 0 {
				result.Reasons = append(result.Reasons, "unsupported_auxiliary_geometry")
			}
		}
	}
	result.normalize(fields, id)
	sort.Slice(result.Reasons, func(i, j int) bool { return result.Reasons[i] < result.Reasons[j] })
	data, err := json.Marshal(result)
	if err != nil {
		return Candidate{}, Code("invalid_projection")
	}
	digest := sha256.Sum256(data)
	result.Fingerprint = hex.EncodeToString(digest[:])
	if err := c.check(); err != nil {
		return Candidate{}, err
	}
	return result, nil
}

func singleTool(raw any) bool {
	items, ok := raw.([]any)
	if !ok || len(items) == 0 || len(items) > 16 {
		return false
	}
	first, ok := number(items[0])
	if !ok {
		return false
	}
	for _, item := range items[1:] {
		n, ok := number(item)
		if !ok || n != first {
			return false
		}
	}
	return true
}
