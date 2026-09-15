//go:build makersvault_native_qualification

// A separately built, manual qualification executable; never a shipping bridge.
// No file-worker dispatch, protocol handler, installer, real profile or vault API.
package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"runtime"
	"strings"
	"time"

	"makersvault/slicer-bridge/internal/presetconsent"
	"makersvault/slicer-bridge/internal/presetui"
)

var sourceRevision = "unrecorded"

type receipt struct {
	SchemaVersion   int    `json:"schema_version"`
	Scope           string `json:"scope"`
	SourceRevision  string `json:"source_revision"`
	OS              string `json:"os"`
	Architecture    string `json:"architecture"`
	GoVersion       string `json:"go_version"`
	Outcome         string `json:"outcome"`
	BrowserAccepted bool   `json:"browser_accepted"`
	ReviewSHA256    string `json:"synthetic_review_sha256,omitempty"`
	GateQualified   bool   `json:"gate_qualified"`
}

func report(out io.Writer, outcome string, browserAccepted bool, digest string) int {
	err := json.NewEncoder(out).Encode(receipt{1, "native-ui-with-synthetic-metadata-only", sourceRevision,
		runtime.GOOS, runtime.GOARCH, runtime.Version(), outcome, browserAccepted, digest, false})
	if err != nil {
		return 1
	}
	return 0
}

func command(args []string, in io.Reader, out io.Writer, interactive bool, launch func(io.Writer) int) int {
	if len(args) != 1 || (args[0] != "--inspect" && args[0] != "--ui-fixture") {
		fmt.Fprintln(out, "Qualification only. Use --inspect (no UI) or --ui-fixture (explicit native UI consent).")
		return 2
	}
	if args[0] == "--inspect" {
		return report(out, "inspection_only_no_native_ui", false, "")
	}
	if !interactive {
		fmt.Fprintln(out, "An interactive terminal is required; redirected input/output is refused.")
		return 2
	}
	if runtime.GOOS != "windows" && runtime.GOOS != "linux" {
		return 2
	}
	const notice = "MANUAL QUALIFICATION ONLY. This opens a real browser and, when requested, a real folder dialog.\n" +
		"All hints/accounts/presets are SYNTHETIC. Selected paths are not read by the metadata backend.\n" +
		"Native OS dialogs may browse providers, touch recent state or access network locations. Do not choose private or remote locations.\n" +
		"No vault is contacted, no profiles imported, no handler registered. Closing the browser tab does not stop the owner.\n" +
		"Ctrl+C stops the owner; session expiry is five minutes. Review the operator checklist before running.\n" +
		"Type START UI TEST and press Enter to authorize this run:\n"
	if _, err := fmt.Fprint(out, notice); err != nil {
		return 1
	}
	line, err := bufio.NewReaderSize(in, 128).ReadSlice('\n')
	if err != nil || strings.TrimSuffix(strings.TrimSuffix(string(line), "\n"), "\r") != "START UI TEST" {
		fmt.Fprintln(out, "No native UI started.")
		return 2
	}
	return launch(out)
}

type owner interface {
	OpenBrowser(context.Context) error
	Close()
	Done() <-chan struct{}
	View() presetconsent.View
	TakeApproved() ([]byte, error)
}

type localOwner struct {
	*presetconsent.LocalServer
	session *presetconsent.Session
}

func (o *localOwner) View() presetconsent.View      { return o.session.View() }
func (o *localOwner) TakeApproved() ([]byte, error) { return o.session.TakeApproved() }
func newOwner(ctx context.Context) (owner, error) {
	s, err := presetconsent.NewUIQualification(ctx)
	if err != nil {
		return nil, err
	}
	h, err := presetconsent.StartLocal(ctx, s)
	if err != nil {
		s.Close()
		return nil, err
	}
	return &localOwner{h, s}, nil
}

func runSession(ctx context.Context, out io.Writer, create func(context.Context) (owner, error)) int {
	if ctx == nil || ctx.Err() != nil {
		report(out, "owner_cancelled_before_start", false, "")
		return 1
	}
	o, err := create(ctx)
	if err != nil {
		report(out, "owner_unavailable", false, "")
		return 1
	}
	defer o.Close()
	if err = o.OpenBrowser(ctx); err != nil {
		report(out, "browser_launch_failed", false, "")
		return 1
	}
	// Poll only the local in-memory session; this is not HTTP polling or tab detection.
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			o.Close()
			return report(out, "owner_cancelled", true, "")
		case <-o.Done():
			stage := o.View().Stage
			if stage != "expired" && stage != "cancelled" {
				stage = "closed_without_consumption"
			}
			return report(out, stage, true, "")
		case <-ticker.C:
			if o.View().Stage == "approved" {
				data, err := o.TakeApproved()
				if err != nil {
					report(out, "approval_revoked", true, "")
					return 1
				}
				sum := sha256.Sum256(data)
				return report(out, "synthetic_preview_consumed", true, hex.EncodeToString(sum[:]))
			}
		}
	}
}

func terminal(file *os.File) bool {
	info, err := file.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}
func main() {
	// Exact early dispatch exists only in this explicitly tagged test executable.
	// The production cmd/slicer-bridge remains untouched. No presetworker dispatch.
	if len(os.Args) == 2 && os.Args[1] == presetui.Argument {
		os.Exit(presetui.Serve(os.Stdin, os.Stdout))
	}
	code := command(os.Args[1:], os.Stdin, os.Stdout, terminal(os.Stdin) && terminal(os.Stdout), func(out io.Writer) int {
		ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
		defer cancel()
		return runSession(ctx, out, newOwner)
	})
	os.Exit(code)
}
