//go:build makersvault_native_qualification

package presetconsent

import (
	"context"
	"runtime"
	"strings"
	"time"

	"makersvault/slicer-bridge/internal/presetfiles"
	"makersvault/slicer-bridge/internal/presetui"
	"makersvault/slicer-bridge/internal/presetworker"
	"makersvault/slicer-bridge/internal/printerpreset"
)

const qualificationName = "SYNTHETIC UI TEST - NOT A PRINTER"

// NewUIQualification exists ONLY in explicitly tagged qualification builds.
// Native dialogs are real; every hint/account/preset is synthetic in-memory data.
// A selected path is never opened, enumerated, or passed to the file worker.
// This does not qualify native hints, readers, profiles or installed app versions.
func NewUIQualification(ctx context.Context) (*Session, error) {
	return newSession(ctx, Config{Origin: "https://qualification.invalid", ExpiresAt: time.Now().Add(MaxLifetime)}, backend{
		hints: func(ctx context.Context) ([]presetfiles.BambuLocation, error) {
			if err := ctx.Err(); err != nil {
				return nil, err
			}
			root := "/makersvault-synthetic-ui-test"
			if runtime.GOOS == "windows" {
				root = `C:\makersvault-synthetic-ui-test`
			}
			return []presetfiles.BambuLocation{{ID: "SYNTHETIC - not an installed location", DataRoot: root}}, nil
		},
		run: qualificationMetadata,
		pick: func(ctx context.Context) (string, error) {
			folder, err := presetui.PickFolder(ctx)
			return folder.Path(), err
		},
	})
}

func qualificationMetadata(ctx context.Context, request presetworker.Request) (presetworker.Response, error) {
	if err := ctx.Err(); err != nil {
		return presetworker.Response{}, err
	}
	// Intentionally never use request.Root for I/O, hints, metadata or diagnostics.
	switch request.Operation {
	case "accounts":
		return presetworker.Response{Accounts: &presetfiles.AccountChoices{Names: []string{"synthetic-account"}}}, nil
	case "discover":
		return presetworker.Response{Discovery: &presetfiles.BambuDiscovery{
			BundleVersion: "1.0.0.0", UserIncluded: request.Account != "",
			Selections: []printerpreset.Selection{{Kind: printerpreset.System, Name: qualificationName}},
		}}, nil
	case "select":
		if len(request.Picks) != 1 || request.Picks[0] != (printerpreset.Selection{Kind: printerpreset.System, Name: qualificationName}) {
			return presetworker.Response{}, Code("qualification_selection_invalid")
		}
		catalog := printerpreset.NewBambu(ctx)
		source := printerpreset.Source{Namespace: "synthetic-ui-qualification", Kind: printerpreset.System, BundleVersion: "1.0.0.0"}
		const machine = `{"type":"machine","name":"SYNTHETIC UI TEST - NOT A PRINTER","instantiation":"true","printable_area":["0x0","200x0","200x200","0x200"],"printable_height":"200","nozzle_diameter":["0.4"],"bed_exclude_area":[]}`
		if err := catalog.Add(source, strings.NewReader(machine)); err != nil {
			return presetworker.Response{}, err
		}
		candidate, err := catalog.Resolve(source.Namespace, printerpreset.System, qualificationName)
		if err != nil {
			return presetworker.Response{}, err
		}
		return presetworker.Response{Candidates: []printerpreset.Candidate{candidate}}, nil
	}
	return presetworker.Response{}, Code("qualification_operation_invalid")
}
