package printerpreset

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"
)

var system = Source{Namespace: "synthetic", Kind: System, ApplicationVersion: "fixture-only"}

func add(t *testing.T, c *Catalog, source Source, fields map[string]any) {
	t.Helper()
	data, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Add(source, bytes.NewReader(data)); err != nil {
		t.Fatal(err)
	}
}

func base(name string) map[string]any {
	return map[string]any{"type": "machine", "name": name, "from": "system", "instantiation": "true",
		"printer_technology": "FFF", "printer_structure": "corexy", "printable_height": "250",
		"nozzle_diameter": []string{"0.4"}, "printable_area": []string{"0x0", "256x0", "256x256", "0x256"}, "bed_exclude_area": []string{}}
}

func resolve(t *testing.T, c *Catalog, name string) Candidate {
	t.Helper()
	out, err := c.Resolve(system.Namespace, System, name)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func fixture(t *testing.T) *Catalog {
	t.Helper()
	c := NewBambu(context.Background())
	// Child first deliberately proves resolution is independent of read order.
	for _, name := range []string{"child", "base", "common"} {
		data, err := os.ReadFile("testdata/" + name + ".json")
		if err != nil {
			t.Fatal(err)
		}
		if err = c.Add(system, bytes.NewReader(data)); err != nil {
			t.Fatal(err)
		}
	}
	return c
}

func TestInheritedProjectionAndPrivacy(t *testing.T) {
	out := resolve(t, fixture(t), "Fixture P1S 0.4")
	if !out.Complete() || *out.Height != 250 || *out.Nozzle != 0.4 || len(out.Exclusions) != 1 || out.Exclusions[0][2] != (Point{18, 28}) {
		t.Fatalf("unexpected projection: %+v", out)
	}
	if !reflect.DeepEqual(out.Bed, []Point{{0, 0}, {256, 0}, {256, 256}, {0, 256}}) || out.SourceOrigin == nil || *out.SourceOrigin != (Point{}) {
		t.Fatal("bed/origin changed")
	}
	if out.Provenance != (Provenance{"inherited", "source", "inherited", "source"}) {
		t.Fatalf("provenance: %+v", out.Provenance)
	}
	data, _ := json.Marshal(out)
	for _, secret := range []string{"FAKE_", "private.invalid", "/fixture/", "machine_start_gcode", "access_code", "hostname", "account", "synthetic"} {
		if bytes.Contains(data, []byte(secret)) {
			t.Fatalf("nonallowlisted data leaked: %s", secret)
		}
	}
	hash := out.Fingerprint
	out.Fingerprint = ""
	data, _ = json.Marshal(out)
	digest := sha256.Sum256(data)
	if hash != hex.EncodeToString(digest[:]) {
		t.Fatal("projection digest mismatch")
	}
}

func TestReturnedProjectionDoesNotMutateCatalog(t *testing.T) {
	c := fixture(t)
	first := resolve(t, c, "Fixture P1S 0.4")
	digest := first.Fingerprint
	first.Bed[0].X = 99
	first.Exclusions[0][0].X = 99
	*first.Height = 42
	second := resolve(t, c, "Fixture P1S 0.4")
	if second.Fingerprint != digest || second.Bed[0].X != 0 || *second.Height != 250 {
		t.Fatal("result mutated source")
	}
}

func TestFingerprintsIgnoreUnrelatedSettingsButTrackGeometry(t *testing.T) {
	project := func(height, secret string) string {
		c := NewBambu(context.Background())
		doc := base("child")
		doc["printable_height"] = height
		doc["password"] = secret
		add(t, c, system, doc)
		return resolve(t, c, "child").Fingerprint
	}
	if project("250", "first") != project("250", "second") {
		t.Fatal("secret affects normalized fingerprint")
	}
	if project("250", "first") == project("249", "first") {
		t.Fatal("geometry omitted from fingerprint")
	}
}

func TestCenteredConcaveBedAndExclusions(t *testing.T) {
	c := NewBambu(context.Background())
	doc := base("centered")
	doc["printable_area"] = []string{"-100x-100", "100x-100", "100x0", "0x0", "0x100", "-100x100"}
	doc["bed_exclude_area"] = []string{"-100x-100", "-80x-100", "-80x-80", "-100x-80"}
	add(t, c, system, doc)
	out := resolve(t, c, "centered")
	if !out.Complete() || len(out.Bed) != 6 || out.Bed[3] != (Point{100, 100}) || *out.SourceOrigin != (Point{-100, -100}) || out.Exclusions[0][2] != (Point{20, 20}) {
		t.Fatalf("wrong translation: %+v", out)
	}
}

func TestCircularPolygonPreservesVerticesAndClosingPoint(t *testing.T) {
	c := NewBambu(context.Background())
	doc := base("round")
	doc["printable_area"] = []string{"0x10", "7x7", "10x0", "7x-7", "0x-10", "-7x-7", "-10x0", "-7x7", "0x10"}
	add(t, c, system, doc)
	out := resolve(t, c, "round")
	if !out.Complete() || len(out.Bed) != 8 || out.Bed[0] != (Point{10, 20}) {
		t.Fatal("polygon was replaced or closing point retained")
	}
}

func TestBambuMultipleExclusionRectangles(t *testing.T) {
	c := fixture(t)
	add(t, c, system, map[string]any{"type": "machine", "name": "multi", "from": "system", "instantiation": "true", "inherits": "fixture-common"})
	out := resolve(t, c, "multi")
	if !out.Complete() || len(out.Exclusions) != 2 || out.Exclusions[1][2] != (Point{8, 256}) {
		t.Fatalf("rectangles not preserved: %+v", out)
	}
}

func TestMissingGeometryIsNotInvented(t *testing.T) {
	for _, field := range []string{"printable_area", "printable_height", "nozzle_diameter", "bed_exclude_area", "printer_technology", "printer_structure"} {
		t.Run(field, func(t *testing.T) {
			c := NewBambu(context.Background())
			doc := base("missing")
			delete(doc, field)
			add(t, c, system, doc)
			out := resolve(t, c, "missing")
			if out.Complete() || len(out.Reasons) == 0 {
				t.Fatal("missing geometry was guessed")
			}
			if field == "bed_exclude_area" && out.Exclusions != nil {
				t.Fatal("unknown exclusions represented as none")
			}
		})
	}
	if (Candidate{}).Complete() {
		t.Fatal("zero projection must not be complete")
	}
}

func TestInvalidAndUnsupportedGeometry(t *testing.T) {
	for _, test := range []struct {
		name, field string
		value       any
	}{
		{"nan", "printable_height", "NaN"}, {"infinite", "printable_height", "Inf"}, {"overflow", "printable_height", "1e999"},
		{"zeroheight", "printable_height", "0"}, {"negativeheight", "printable_height", "-1"}, {"bigheight", "printable_height", "10001"},
		{"smallnozzle", "nozzle_diameter", []string{"0.01"}}, {"bignozzle", "nozzle_diameter", []string{"11"}}, {"twonozzles", "nozzle_diameter", []string{"0.4", "0.4"}},
		{"bowtie", "printable_area", []string{"0x0", "10x10", "0x10", "10x0"}},
		{"flat", "printable_area", []string{"0x0", "5x0", "10x0"}},
		{"repeated", "printable_area", []string{"0x0", "10x0", "10x0", "0x10"}},
		{"backtrack", "printable_area", []string{"0x0", "10x0", "5x0", "10x10", "0x10"}},
		{"badpoint", "printable_area", []string{"0x0", "10xnope", "0x10"}},
		{"bigspan", "printable_area", []string{"-10000x0", "10000x0", "10000x10", "-10000x10"}},
		{"badexclude", "bed_exclude_area", []string{"0x0", "10x0", "0x10"}},
		{"trapezoid", "bed_exclude_area", []string{"0x0", "10x0", "8x10", "0x10"}},
		{"resin", "printer_technology", "SLA"}, {"belt", "printer_structure", "belt"},
		{"extruderarea", "extruder_printable_area", []string{"0x0"}}, {"multipletools", "printer_extruder_id", []string{"1", "2"}},
		{"physicaltools", "physical_extruder_map", []string{"0", "1"}},
		{"wrapping", "wrapping_exclude_area", []string{"0x0", "1x0", "1x1", "0x1"}},
		{"headzone", "head_wrap_detect_zone", []string{"0x0"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			c := NewBambu(context.Background())
			doc := base("bad")
			doc[test.field] = test.value
			add(t, c, system, doc)
			if out := resolve(t, c, "bad"); out.Complete() || len(out.Reasons) == 0 {
				t.Fatalf("accepted %s", test.name)
			}
		})
	}
}

func TestResolveInheritanceFailures(t *testing.T) {
	for _, test := range []struct {
		name    string
		parents map[string]string
		want    Code
	}{
		{"missing", map[string]string{"a": "missing"}, "missing_parent"},
		{"cycle", map[string]string{"a": "b", "b": "a"}, "inheritance_cycle"},
		{"self", map[string]string{"a": "a"}, "inheritance_cycle"},
		{"path", map[string]string{"a": "../../private.json"}, "missing_parent"},
		{"url", map[string]string{"a": "https://private.invalid/profile.json"}, "missing_parent"},
	} {
		t.Run(test.name, func(t *testing.T) {
			c := NewBambu(context.Background())
			for name, parent := range test.parents {
				doc := base(name)
				doc["inherits"] = parent
				add(t, c, system, doc)
			}
			_, err := c.Resolve(system.Namespace, System, "a")
			if err != test.want {
				t.Fatalf("got %v, want %v", err, test.want)
			}
		})
	}
}

func TestInheritanceDepthBoundary(t *testing.T) {
	for _, length := range []int{16, 17} {
		c := NewBambu(context.Background())
		for i := 0; i < length; i++ {
			doc := base(fmt.Sprint(i))
			if i+1 < length {
				doc["inherits"] = fmt.Sprint(i + 1)
			}
			add(t, c, system, doc)
		}
		_, err := c.Resolve(system.Namespace, System, "0")
		if length == 16 && err != nil || length == 17 && err != Code("inheritance_depth_exceeded") {
			t.Fatalf("depth %d: %v", length, err)
		}
	}
}

func TestNamespaceAndUserParentAmbiguity(t *testing.T) {
	c := NewBambu(context.Background())
	parent := base("parent")
	add(t, c, system, parent)
	user := Source{Namespace: system.Namespace, Kind: User}
	child := base("custom")
	child["from"] = "user"
	child["inherits"] = "parent"
	child["nozzle_diameter"] = []string{"0.6"}
	add(t, c, user, child)
	out, err := c.Resolve(user.Namespace, User, "custom")
	if err != nil || !out.Complete() || *out.Nozzle != 0.6 || out.Source.Kind != User {
		t.Fatalf("user projection: %+v %v", out, err)
	}
	parent["from"] = "user"
	add(t, c, user, parent)
	if _, err = c.Resolve(user.Namespace, User, "custom"); err != Code("ambiguous_parent") {
		t.Fatalf("ambiguous parent: %v", err)
	}
	if _, err = c.Resolve("other", System, "parent"); err != Code("preset_not_found") {
		t.Fatal("namespace escaped")
	}
}

func TestSystemCannotInheritUserAndTemplatesNotSelectable(t *testing.T) {
	c := NewBambu(context.Background())
	doc := base("user-parent")
	doc["from"] = "user"
	add(t, c, Source{Namespace: system.Namespace, Kind: User}, doc)
	doc = base("system-child")
	doc["inherits"] = "user-parent"
	add(t, c, system, doc)
	if _, err := c.Resolve(system.Namespace, System, "system-child"); err != Code("missing_parent") {
		t.Fatal("system accepted user parent")
	}
	if _, err := fixture(t).Resolve(system.Namespace, System, "fixture-base"); err != Code("not_selectable") {
		t.Fatal("template selectable")
	}
	doc = base("unknown")
	delete(doc, "instantiation")
	add(t, c, system, doc)
	if _, err := c.Resolve(system.Namespace, System, "unknown"); err != Code("not_selectable") {
		t.Fatal("missing instantiation guessed")
	}
}

func TestIncludesNeverResolveFilesOrUnknownTemplates(t *testing.T) {
	for _, include := range []string{"https://private.invalid/file", "../../private.json", "base template printable_area", "base template machine_start_gcode/extra"} {
		c := NewBambu(context.Background())
		doc := base("child")
		doc["include"] = []string{include}
		add(t, c, system, doc)
		if _, err := c.Resolve(system.Namespace, System, "child"); err != Code("unsupported_include") {
			t.Fatalf("unsafe include accepted: %v", err)
		}
	}
}

func TestDuplicateInvalidOrTruncatedCatalogFailsClosed(t *testing.T) {
	c := NewBambu(context.Background())
	doc := base("child")
	add(t, c, system, doc)
	data, _ := json.Marshal(doc)
	if err := c.Add(system, bytes.NewReader(data)); err != Code("ambiguous_identity") {
		t.Fatalf("duplicate: %v", err)
	}
	if _, err := c.Resolve(system.Namespace, System, "child"); err != Code("catalog_incomplete") {
		t.Fatal("partial catalog resolved")
	}
}

func TestInvalidJSONDoesNotLeakSourceValues(t *testing.T) {
	for _, raw := range []string{
		`{"name":"PRIVATE_VALUE",`, `{"name":"a","name":"b"}`, `{} {}`,
		`{"ignored":{"secret":"PRIVATE_VALUE","secret":"other"}}`,
		`{"printable_height":{"secret":"PRIVATE_VALUE"}}`, `[]`, `null`, "\xff",
		`{"type":"machine","name":"bad\u0000value"}`, `{"type":"machine","name":"x","from":"user"}`,
		`{"type":"machine","name":"future","schema_version":999}`, `{"format_version":1}`,
	} {
		c := NewBambu(context.Background())
		err := c.Add(system, strings.NewReader(raw))
		if err == nil || strings.Contains(err.Error(), "PRIVATE_VALUE") {
			t.Fatalf("invalid input/error: %v", err)
		}
	}
}

func TestJSONResourceBudgets(t *testing.T) {
	for _, raw := range []string{
		`{"ignored":` + strings.Repeat("[", 33) + `0` + strings.Repeat("]", 33) + `}`,
		`{"ignored":[` + strings.Repeat(`0,`, 65536) + `0]}`,
		`{"printable_area":[` + strings.Repeat(`"0x0",`, 256) + `"0x0"]}`,
	} {
		c := NewBambu(context.Background())
		if err := c.Add(system, strings.NewReader(raw)); err == nil {
			t.Fatal("resource budget not enforced")
		}
	}
}

func TestFileTotalAndCountBudgets(t *testing.T) {
	for _, test := range []struct {
		name  string
		bytes int64
		count int
		input string
		want  Code
	}{
		{"file", 0, 0, strings.Repeat(" ", MaxFileBytes+1), "file_bytes_exceeded"},
		{"total", MaxTotalBytes, 0, "x", "total_bytes_exceeded"},
		{"count", 0, MaxFiles, "{}", "file_count_exceeded"},
	} {
		t.Run(test.name, func(t *testing.T) {
			c := NewBambu(context.Background())
			c.bytes = test.bytes
			c.files = test.count
			if err := c.Add(system, strings.NewReader(test.input)); err != test.want {
				t.Fatalf("got %v", err)
			}
		})
	}
}

type brokenReader struct{}

func (brokenReader) Read([]byte) (int, error) { return 0, errors.New("PRIVATE_READER_PATH") }

type cancelReader struct{ cancel context.CancelFunc }

func (r cancelReader) Read(p []byte) (int, error) { r.cancel(); return copy(p, "{"), nil }

func TestCancellationDeadlineAndReadError(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	c := NewBambu(ctx)
	if err := c.Add(system, cancelReader{cancel}); err != Code("cancelled") {
		t.Fatalf("cancel: %v", err)
	}
	c = NewBambu(context.Background())
	c.started = time.Now().Add(-MaxDuration)
	if err := c.Add(system, strings.NewReader("{}")); err != Code("time_budget_exceeded") {
		t.Fatalf("time: %v", err)
	}
	c = NewBambu(context.Background())
	if err := c.Add(system, brokenReader{}); err != Code("read_failed") {
		t.Fatalf("reader error leaked: %v", err)
	}
}

func FuzzBambuProjection(f *testing.F) {
	seed, _ := json.Marshal(base("fuzz"))
	f.Add(seed)
	f.Add([]byte(`{"name":"x","ignored":{"duplicate":1,"duplicate":2}}`))
	f.Fuzz(func(t *testing.T, data []byte) {
		if len(data) > 16384 {
			return
		}
		c := NewBambu(context.Background())
		err := c.Add(system, bytes.NewReader(data))
		if err != nil {
			if _, ok := err.(Code); !ok {
				t.Fatalf("unredacted error type: %T", err)
			}
			return
		}
		for id := range c.documents {
			out, err := c.Resolve(id.namespace, id.kind, id.name)
			if err != nil {
				continue
			}
			if _, err = json.Marshal(out); err != nil {
				t.Fatal("nonfinite projection")
			}
			if out.Complete() && (!simple(out.Bed) || *out.Height <= 0 || *out.Nozzle < 0.05) {
				t.Fatal("invalid complete geometry")
			}
		}
	})
}

var _ io.Reader = brokenReader{}
