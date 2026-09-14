package presetfiles

import (
	"context"
	"runtime"
	"testing"

	"makersvault/slicer-bridge/internal/printerpreset"
)

func TestDiscoveryResponseValidation(t *testing.T) {
	valid := BambuDiscovery{BundleVersion: "1.2.3.4", HiddenMachines: 1, ExcludedScripts: 1, Selections: []printerpreset.Selection{{Kind: printerpreset.System, Name: "Printer"}}}
	if !valid.Validate(false) {
		t.Fatal("valid discovery rejected")
	}
	for _, edit := range []func(*BambuDiscovery){
		func(d *BambuDiscovery) { d.ApplicationVersion = "1.2.3.4" },
		func(d *BambuDiscovery) { d.HiddenMachines = -1 },
		func(d *BambuDiscovery) { d.ExcludedScripts = MaxEntries },
		func(d *BambuDiscovery) { d.Selections = nil },
		func(d *BambuDiscovery) { d.Selections = append(d.Selections, d.Selections[0]) },
		func(d *BambuDiscovery) {
			d.Selections = []printerpreset.Selection{{Kind: printerpreset.User, Name: "Printer"}}
		},
		func(d *BambuDiscovery) {
			d.Selections = []printerpreset.Selection{{Kind: printerpreset.System, Name: "Printer template machine_start_gcode"}}
		},
	} {
		bad := valid
		edit(&bad)
		if bad.Validate(false) {
			t.Fatal("invalid discovery accepted")
		}
	}
}

func TestDiscoveryPlatformAndCancellationBeforeIO(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if got, err := DiscoverBambu(ctx, "/not-a-root", ""); got != nil || err != Code("source_cancelled") {
		t.Fatal(err)
	}
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		if got, err := DiscoverBambu(context.Background(), "/not-a-root", ""); got != nil || err != Code("source_platform_unsupported") {
			t.Fatal(err)
		}
	}
}
