package printerpreset

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func TestIndexedIdentityBindingPoisonsCatalog(t *testing.T) {
	c := NewBambu(context.Background())
	if err := c.AddIndexed(system, "Expected", strings.NewReader(`{"type":"machine","name":"Actual","instantiation":true}`)); err != Code("manifest_identity_mismatch") {
		t.Fatal(err)
	}
	if _, err := c.Selections(system.Namespace); err != Code("catalog_incomplete") {
		t.Fatal(err)
	}
	for _, source := range []Source{{Namespace: "x", Kind: User}, system} {
		c := NewBambu(context.Background())
		if err := c.AddIndexed(source, "", strings.NewReader(`{}`)); err != Code("invalid_source") {
			t.Fatal(err)
		}
	}
}

func TestSelectionsExactOrderedAndNotGeometryClaims(t *testing.T) {
	c := NewBambu(context.Background())
	for _, raw := range []string{
		`{"type":"machine","name":"z","instantiation":"true","inherits":"base"}`,
		`{"type":"machine","name":"base","instantiation":false}`,
		`{"type":"machine","name":"missing-instantiation"}`,
		`{"type":"machine","name":"a","instantiation":true}`,
	} {
		if err := c.Add(system, strings.NewReader(raw)); err != nil {
			t.Fatal(err)
		}
	}
	got, err := c.Selections(system.Namespace)
	if err != nil || !reflect.DeepEqual(got, []Selection{{System, "a"}, {System, "z"}}) {
		t.Fatalf("%v %v", got, err)
	}
	candidate, err := c.Resolve(system.Namespace, System, "z")
	if err != nil || candidate.Complete() || len(candidate.Reasons) == 0 {
		t.Fatal("incomplete geometry invented", err)
	}
}

func TestSelectionsValidateHiddenParentChains(t *testing.T) {
	c := NewBambu(context.Background())
	if err := c.Add(system, strings.NewReader(`{"type":"machine","name":"hidden","instantiation":false,"inherits":"absent"}`)); err != nil {
		t.Fatal(err)
	}
	if got, err := c.Selections(system.Namespace); got != nil || err != Code("missing_parent") {
		t.Fatalf("%v %v", got, err)
	}
}

func TestInstantiationMalformedIsNotSilentlyHidden(t *testing.T) {
	for _, value := range []string{`null`, `1`, `"TRUE"`, `[]`, `""`} {
		c := NewBambu(context.Background())
		if err := c.Add(system, strings.NewReader(`{"type":"machine","name":"x","instantiation":`+value+`}`)); err != Code("invalid_instantiation") {
			t.Fatal(value, err)
		}
	}
}

func TestDiscoveryRejectsCaseAliasedIdentityAndSchema(t *testing.T) {
	for _, suffix := range []string{`"Type":"filament"`, `"Name":"Different"`, `"Schema_Version":99`, `"ignored":{"a":1,"A":2}`, `"naſe":"x"`} {
		c := NewBambu(context.Background())
		if err := c.AddIndexed(system, "x", strings.NewReader(`{"type":"machine","name":"x",`+suffix+`}`)); err != Code("invalid_json_key") {
			t.Fatal(suffix, err)
		}
	}
}

func TestIndexAndProfilesShareFileByteAndTimeBudgets(t *testing.T) {
	c := NewBambu(context.Background())
	index := "{}"
	if _, err := c.ReadIndex(strings.NewReader(index)); err != nil {
		t.Fatal(err)
	}
	if c.files != 1 || c.bytes != 2 {
		t.Fatal("index not charged")
	}
	if err := c.Add(system, strings.NewReader(`{"type":"machine","name":"x"}`)); err != nil {
		t.Fatal(err)
	}
	if c.files != 2 || c.bytes <= 2 {
		t.Fatal("profile reset budget")
	}
	c.bytes = MaxTotalBytes - 1
	if _, err := c.ReadIndex(strings.NewReader("12")); err != Code("total_bytes_exceeded") {
		t.Fatal(err)
	}
	if _, err := c.Selections(system.Namespace); err != Code("catalog_incomplete") {
		t.Fatal(err)
	}
	c = NewBambu(context.Background())
	c.files = MaxFiles
	if _, err := c.ReadIndex(strings.NewReader(index)); err != Code("file_count_exceeded") {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	c = NewBambu(ctx)
	cancel()
	if _, err := c.ReadIndex(strings.NewReader(index)); err != Code("cancelled") {
		t.Fatal(err)
	}
	c = NewBambu(context.Background())
	if _, err := c.ReadIndex(brokenReader{}); err != Code("read_failed") {
		t.Fatal(err)
	}
}

func FuzzBambuIndexedSelections(f *testing.F) {
	f.Add([]byte(`{"type":"machine","name":"fixture","instantiation":true}`), "fixture")
	f.Add([]byte(`{"type":"machine","name":"fixture","inherits":"fixture"}`), "fixture")
	f.Fuzz(func(t *testing.T, data []byte, expected string) {
		if len(data) > 16384 || len(expected) > 800 {
			return
		}
		c := NewBambu(context.Background())
		err := c.AddIndexed(system, expected, strings.NewReader(string(data)))
		if err != nil {
			if _, ok := err.(Code); !ok {
				t.Fatal("unredacted error")
			}
			return
		}
		picks, err := c.Selections(system.Namespace)
		if err != nil {
			if picks != nil {
				t.Fatal("partial choices")
			}
			return
		}
		for _, pick := range picks {
			if pick.Name != expected || pick.Kind != System {
				t.Fatal("identity not bound")
			}
			candidate, err := c.Resolve(system.Namespace, pick.Kind, pick.Name)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := json.Marshal(candidate); err != nil {
				t.Fatal(err)
			}
		}
	})
}
