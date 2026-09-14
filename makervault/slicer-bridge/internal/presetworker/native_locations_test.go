package presetworker

import (
	"bytes"
	"context"
	"encoding/json"
	"runtime"
	"strings"
	"testing"
	"time"

	"makersvault/slicer-bridge/internal/presetfiles"
)

func TestNativeLocationPlanStrict(t *testing.T) {
	valid := []wireLocation{{"BambuStudio", `C:\synthetic\BambuStudio`}, {"BambuStudioBeta", `C:\synthetic\BambuStudioBeta`}, {"BambuStudioInternal", `C:\synthetic\BambuStudioInternal`}}
	if !validNativeLocations(valid) {
		t.Fatal("known-root plan rejected")
	}
	for _, index := range []int{0, 1, 2} {
		for _, field := range []string{"id", "root"} {
			changed := append([]wireLocation(nil), valid...)
			if field == "id" {
				changed[index].ID = "custom"
			} else {
				changed[index].DataRoot = `C:\different\BambuStudio`
			}
			if validNativeLocations(changed) {
				t.Fatal("mixed/custom root plan accepted")
			}
		}
	}
	for _, invalid := range [][]wireLocation{nil, valid[:2], append(append([]wireLocation(nil), valid...), valid[0]),
		{{"BambuStudio", `\\server\share\BambuStudio`}, valid[1], valid[2]}} {
		if validNativeLocations(invalid) {
			t.Fatal("unsafe plan accepted")
		}
	}
}

func TestNativeLocationWireHasNoSuppliedAuthority(t *testing.T) {
	for _, req := range []Request{
		{Operation: "native-locations", Root: "/private"}, {Operation: "native-locations", Account: "default"},
		{Operation: "native-locations", Picks: []Pick{{Name: "private"}}},
		{Operation: "native-locations", Inputs: []presetfiles.Input{{Root: "/private"}}},
	} {
		if _, _, err := marshalRequest(req); err == nil {
			t.Fatal("native lookup gained caller path authority")
		}
	}
	var output bytes.Buffer
	Serve(strings.NewReader(`{"Version":1,"Operation":"native-locations","Hints":{"HOME":"/private"}}`), &output)
	if !strings.Contains(output.String(), "worker_request_invalid") {
		t.Fatal("worker accepted hint injection")
	}
	data, _ := json.Marshal(envelope{Version: 1, Locations: []wireLocation{{"BambuStudio", `C:\private\BambuStudio`}}})
	for _, operation := range []string{"list", "accounts", "manifest", "location", "discover", "select", "project", "native-locations"} {
		if _, err := decodeResponse(data, wireRequest{Version: 1, Operation: operation}); err != Code("worker_response_invalid") {
			t.Fatal("partial or cross-operation plan accepted")
		}
	}
	public, _ := json.Marshal(Response{Locations: []presetfiles.BambuLocation{{ID: "private", DataRoot: "/private"}}})
	if string(public) != "{}" {
		t.Fatal("public response serialized root authority")
	}
}

func TestNativeLocationsWithoutRealHints(t *testing.T) {
	if runtime.GOOS == "linux" {
		t.Setenv("XDG_CONFIG_HOME", "/synthetic/not-present")
		locations, err := NativeLocations(context.Background())
		if err != nil || len(locations) != 3 || locations[0].DataRoot != "/synthetic/not-present/BambuStudio" {
			t.Fatal(err)
		}
		// The sanitized Linux worker must not guess from missing HOME/XDG.
		if _, err := Run(context.Background(), Request{Operation: "native-locations"}); err != Code("source_platform_unsupported") {
			t.Fatal(err)
		}
	} else if runtime.GOOS != "windows" {
		if _, err := NativeLocations(context.Background()); err != Code("source_platform_unsupported") {
			t.Fatal(err)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := NativeLocations(ctx); err == nil {
		t.Fatal("cancelled native hint request proceeded")
	}
}

func TestNativeLocationWorkerDeadlineAndSlot(t *testing.T) {
	// Exact native-locations frame through the existing supervisor, with an
	// intentionally hung child. Does not claim to reproduce a Windows Shell hang.
	data, _, err := marshalRequest(Request{Operation: "native-locations"})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	if result, err := supervise(ctx, fixtureCommand(t, "hang"), data); result != nil || err != Code("worker_timeout") {
		t.Fatal(err)
	}
	waitIdle(t)
}

func FuzzNativeLocationPlan(f *testing.F) {
	for _, seed := range []string{`C:\synthetic`, `\\server\share`, `/tmp`, `C:\NUL`, ``} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, root string) {
		if len(root) > 4096 {
			return
		}
		plan := []wireLocation{{"BambuStudio", root + `\BambuStudio`}, {"BambuStudioBeta", root + `\BambuStudioBeta`}, {"BambuStudioInternal", root + `\BambuStudioInternal`}}
		_, err := presetfiles.PlanBambuLocations(presetfiles.LocationHints{Platform: "windows", RoamingAppData: root})
		if validNativeLocations(plan) != (err == nil) {
			t.Fatal("parent/native plan parity lost")
		}
	})
}
