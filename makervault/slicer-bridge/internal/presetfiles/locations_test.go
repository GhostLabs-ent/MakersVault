package presetfiles

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func TestKnownBambuLocationsAreUnobservedAndExplicit(t *testing.T) {
	for _, tc := range []struct {
		hints LocationHints
		first string
	}{
		{LocationHints{Platform: "windows", RoamingAppData: `C:\Users\Maker\AppData\Roaming`}, `C:\Users\Maker\AppData\Roaming\BambuStudio`},
		{LocationHints{Platform: "linux", UserHome: "/home/maker"}, "/home/maker/.config/BambuStudio"},
		{LocationHints{Platform: "linux", ConfigHome: "/custom/config", UserHome: "/ignored"}, "/custom/config/BambuStudio"},
	} {
		locations, err := PlanBambuLocations(tc.hints)
		if err != nil || len(locations) != 3 || locations[0].DataRoot != tc.first ||
			locations[1].DataRoot != tc.first+"Beta" || locations[2].DataRoot != tc.first+"Internal" {
			t.Fatalf("unexpected plan: %v %v", locations, err)
		}
		for _, location := range locations {
			if !locationRoot(tc.hints.Platform, location.DataRoot) {
				t.Fatal("invalid planned path")
			}
		}
	}
	locations, err := PlanBambuLocations(LocationHints{Platform: "linux", CustomDataRoot: "/chosen/profile-data", ConfigHome: "invalid-unused"})
	if err != nil || len(locations) != 1 || locations[0].ID != "custom" || locations[0].DataRoot != "/chosen/profile-data" {
		t.Fatal("custom root did not replace known-root plan")
	}
}

func TestBambuLocationHintsRejectPathsWithoutFallback(t *testing.T) {
	for _, hints := range []LocationHints{
		{Platform: "darwin", CustomDataRoot: "/explicit-but-deferred"}, {},
		{Platform: "linux"}, {Platform: "windows"},
		{Platform: "linux", ConfigHome: "relative", UserHome: "/valid-but-not-fallback"},
		{Platform: "linux", CustomDataRoot: "relative", UserHome: "/valid-but-not-fallback"},
		{Platform: "linux", UserHome: "/"}, {Platform: "linux", ConfigHome: "/tmp/../etc"},
		{Platform: "linux", ConfigHome: "/tmp/"}, {Platform: "linux", ConfigHome: "//host/share"},
		{Platform: "linux", ConfigHome: "/tmp/\x00private"}, {Platform: "linux", ConfigHome: "/tmp/\\private"},
		{Platform: "linux", ConfigHome: "/" + strings.Repeat("x", 4085)},
		{Platform: "windows", RoamingAppData: `\\server\share`},
		{Platform: "windows", RoamingAppData: `C:\`}, {Platform: "windows", RoamingAppData: `C:relative`},
		{Platform: "windows", RoamingAppData: `C:\tmp\..\private`},
		{Platform: "windows", RoamingAppData: `C:\NUL`},
	} {
		if locations, err := PlanBambuLocations(hints); locations != nil || err == nil {
			t.Fatalf("unsafe/implicit fallback plan: %v", locations)
		}
	}
}

func TestLocationPathsCannotArriveThroughJSON(t *testing.T) {
	hints := LocationHints{Platform: "linux", CustomDataRoot: "/private/root"}
	location := BambuLocation{ID: "custom", DataRoot: "/private/root"}
	for _, value := range []any{hints, location} {
		data, err := json.Marshal(value)
		if err != nil || string(data) != "{}" {
			t.Fatal("location authority serialized")
		}
	}
	var decoded LocationHints
	if err := json.Unmarshal([]byte(`{"Platform":"linux","CustomDataRoot":"/private/root"}`), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.Platform != "" || decoded.CustomDataRoot != "" {
		t.Fatal("JSON conferred location authority")
	}
}

func TestLocationCancellationBeforeFilesystem(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if result, err := InspectBambuLocation(ctx, "/never-read", "default"); result != nil || err != Code("source_cancelled") {
		t.Fatal(err)
	}
}

func TestLocationObservationValidation(t *testing.T) {
	m, err := ParseBambuManifest(context.Background(), []byte(manifestFixture))
	if err != nil {
		t.Fatal(err)
	}
	valid := LocationInspection{Manifest: *m, UserIncluded: true, UserFiles: []string{"a.json", "b.json"}}
	if !valid.Validate(true) || valid.Validate(false) {
		t.Fatal("account presence mismatch")
	}
	for _, files := range [][]string{nil, {"../a.json"}, {"a.json", "a.json"}, {"a.json", "A.JSON"}, {"b.json", "a.json"}, {"NUL.json"}} {
		value := valid
		value.UserFiles = files
		if value.Validate(true) {
			t.Fatal("bad user index accepted")
		}
	}
	valid.ApplicationVersion = "02.08.00.05"
	if valid.Validate(true) {
		t.Fatal("invented observed app version accepted")
	}
}

func FuzzBambuLocations(f *testing.F) {
	f.Add("linux", "/home/maker", "", "")
	f.Add("windows", "", `C:\Users\Maker\AppData\Roaming`, "")
	f.Add("darwin", "", "", "/tmp/custom")
	f.Fuzz(func(t *testing.T, platform, home, config, custom string) {
		locations, err := PlanBambuLocations(LocationHints{Platform: platform, UserHome: home, ConfigHome: config, RoamingAppData: config, CustomDataRoot: custom})
		if err != nil {
			if locations != nil {
				t.Fatal("partial location plan")
			}
			return
		}
		if len(locations) != 1 && len(locations) != 3 {
			t.Fatal("unbounded location plan")
		}
		for _, location := range locations {
			if !locationRoot(platform, location.DataRoot) {
				t.Fatal("unsafe planned location")
			}
		}
	})
}
