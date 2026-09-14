// Package presetworker supervises a fixed, single-use self worker. It is not yet
// wired into the bridge executable and introduces no remote/CLI authority.
package presetworker

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"io"
	"strings"
	"unicode"
	"unicode/utf8"

	"makersvault/slicer-bridge/internal/presetfiles"
	"makersvault/slicer-bridge/internal/printerpreset"
)

const (
	Argument         = "--internal-preset-worker-v1"
	MaxRequestBytes  = 4 << 20
	MaxResponseBytes = 2 << 20
	MaxStderrBytes   = 64 << 10
	MaxSelected      = presetfiles.MaxSelected
)

type Code string

func (c Code) Error() string { return string(c) }

type Pick = printerpreset.Selection

// Request is local-only. No environment/command/URL is accepted. Paths travel
// only through private anonymous stdin to the exact self executable, never JSON
// decoded directly into this public type or through protocol arguments.
type Request struct {
	Operation string              `json:"-"` // accounts, list, manifest, location, discover, select or project
	Root      string              `json:"-"`
	Account   string              `json:"-"` // location/discover/select; empty explicitly means system-only
	Inputs    []presetfiles.Input `json:"-"`
	Picks     []Pick              `json:"-"`
}

type Response struct {
	Accounts   *presetfiles.AccountChoices     `json:"accounts,omitempty"`  // LOCAL-ONLY names, never an import payload
	Names      []string                        `json:"names,omitempty"`     // local-only listing; never import payload
	Manifest   *presetfiles.BambuManifest      `json:"manifest,omitempty"`  // local-only index, not selectable printers
	Location   *presetfiles.LocationInspection `json:"location,omitempty"`  // local-only, no root/account identity
	Discovery  *presetfiles.BambuDiscovery     `json:"discovery,omitempty"` // local choices, not import payload
	Candidates []printerpreset.Candidate       `json:"candidates,omitempty"`
}

type wireInput struct {
	Root   string
	Files  []string
	Source printerpreset.Source
}
type wireRequest struct {
	Version   int
	Operation string
	Root      string
	Account   string
	Inputs    []wireInput
	Picks     []Pick
}
type envelope struct {
	Version  int
	Code     Code
	Response Response
}

func boundedText(text string, maximum int, empty bool) bool {
	if !utf8.ValidString(text) || len(text) > maximum || (!empty && text == "") {
		return false
	}
	for _, r := range text {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

func validateRequest(req wireRequest) bool {
	if req.Version != 1 {
		return false
	}
	if req.Operation == "select" {
		return len(req.Inputs) == 0 && boundedText(req.Root, 4096, false) &&
			boundedText(req.Account, 255, true) && !strings.ContainsAny(req.Account, `/\:`) &&
			len(req.Picks) > 0 && presetfiles.ValidSelections(req.Picks, MaxSelected)
	}
	if req.Operation == "location" || req.Operation == "discover" {
		return len(req.Inputs) == 0 && len(req.Picks) == 0 && boundedText(req.Root, 4096, false) &&
			boundedText(req.Account, 255, true) && !strings.ContainsAny(req.Account, `/\:`)
	}
	if req.Account != "" {
		return false
	}
	if req.Operation == "list" || req.Operation == "manifest" || req.Operation == "accounts" {
		return len(req.Inputs) == 0 && len(req.Picks) == 0 && boundedText(req.Root, 4096, false)
	}
	if req.Operation != "project" || req.Root != "" || len(req.Inputs) == 0 || len(req.Inputs) > 2 ||
		len(req.Picks) == 0 || len(req.Picks) > MaxSelected {
		return false
	}
	count := 0
	for _, input := range req.Inputs {
		if !boundedText(input.Root, 4096, false) || len(input.Files) == 0 ||
			!boundedText(input.Source.Namespace, 800, false) ||
			!boundedText(input.Source.ApplicationVersion, 800, true) ||
			!boundedText(input.Source.BundleVersion, 800, true) {
			return false
		}
		count += len(input.Files)
		if count > printerpreset.MaxFiles {
			return false
		}
		for _, name := range input.Files {
			if !boundedText(name, 255, false) {
				return false
			}
		}
	}
	seen := map[Pick]bool{}
	for _, pick := range req.Picks {
		if !boundedText(pick.Name, 800, false) || utf8.RuneCountInString(pick.Name) > 200 ||
			(pick.Kind != printerpreset.System && pick.Kind != printerpreset.User) || seen[pick] {
			return false
		}
		seen[pick] = true
	}
	return true
}

func marshalRequest(req Request) ([]byte, wireRequest, error) {
	if len(req.Inputs) > 2 || len(req.Picks) > MaxSelected {
		return nil, wireRequest{}, Code("worker_request_limit")
	}
	wire := wireRequest{Version: 1, Operation: req.Operation, Root: req.Root, Account: req.Account, Picks: req.Picks}
	for _, input := range req.Inputs {
		wire.Inputs = append(wire.Inputs, wireInput{input.Root, input.Files, input.Source})
	}
	if !validateRequest(wire) {
		return nil, wireRequest{}, Code("worker_request_invalid")
	}
	data, err := json.Marshal(wire)
	if err != nil || len(data) > MaxRequestBytes {
		return nil, wireRequest{}, Code("worker_request_limit")
	}
	return data, wire, nil
}

// Strict private framing: one JSON value, bounded token/depth/key counts, no
// duplicate or unknown keys. This is NOT the future API's snapshot validator.
func decode(data []byte, destination any) error {
	if !utf8.Valid(data) {
		return Code("worker_frame_invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	tokens := 0
	var visit func(int) error
	visit = func(depth int) error {
		tokens++
		if depth > 16 || tokens > 250000 {
			return Code("worker_frame_invalid")
		}
		token, err := decoder.Token()
		if err != nil {
			return Code("worker_frame_invalid")
		}
		delim, container := token.(json.Delim)
		if !container {
			return nil
		}
		switch delim {
		case '{':
			keys := map[string]bool{}
			for decoder.More() {
				token, err := decoder.Token()
				key, ok := token.(string)
				// All schema keys are ASCII. Reject Unicode aliases that Go's
				// case-insensitive struct decoder could otherwise match (long s).
				for _, r := range key {
					if r > unicode.MaxASCII {
						return Code("worker_frame_invalid")
					}
				}
				key = strings.ToLower(key) // encoding/json matches struct fields without case
				if err != nil || !ok || keys[key] || len(keys) >= 64 {
					return Code("worker_frame_invalid")
				}
				keys[key] = true
				if err := visit(depth + 1); err != nil {
					return err
				}
			}
			end, err := decoder.Token()
			if err != nil || end != json.Delim('}') {
				return Code("worker_frame_invalid")
			}
		case '[':
			for decoder.More() {
				if err := visit(depth + 1); err != nil {
					return err
				}
			}
			end, err := decoder.Token()
			if err != nil || end != json.Delim(']') {
				return Code("worker_frame_invalid")
			}
		default:
			return Code("worker_frame_invalid")
		}
		return nil
	}
	if err := visit(0); err != nil {
		return err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return Code("worker_frame_invalid")
	}
	decoder = json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return Code("worker_frame_invalid")
	}
	return nil
}

var scanCodes = map[Code]bool{}

func init() {
	for _, code := range strings.Fields(`source_path_invalid source_selection_invalid source_unavailable
		source_unsafe source_changed source_filesystem_unsupported source_boundary_unavailable
		source_platform_unsupported source_entry_limit_exceeded source_file_limit_exceeded
		source_ambiguous_filename source_time_budget_exceeded source_cancelled file_bytes_exceeded
		total_bytes_exceeded file_count_exceeded missing_parent ambiguous_parent ambiguous_identity
		inheritance_cycle inheritance_depth_exceeded not_selectable preset_not_found catalog_incomplete
		worker_source_rejected worker_request_invalid worker_request_limit worker_response_limit`) {
		scanCodes[Code(code)] = true
	}
	for _, code := range strings.Fields(`manifest_invalid manifest_unsupported manifest_bytes_exceeded
		manifest_structure_limit manifest_entry_limit manifest_selection_invalid manifest_identity_mismatch
		invalid_instantiation invalid_machine_identity invalid_identity_field source_kind_mismatch
		unsupported_source_schema unsupported_include unsupported_user_version`) {
		scanCodes[Code(code)] = true
	}
}

func safeCode(err error) Code {
	var code Code
	switch e := err.(type) {
	case presetfiles.Code:
		code = Code(e)
	case printerpreset.Code:
		code = Code(e)
	case Code:
		code = e
	}
	if scanCodes[code] {
		return code
	}
	return "worker_source_rejected"
}

func decodeResponse(data []byte, request wireRequest) (Response, error) {
	var result envelope
	if err := decode(data, &result); err != nil || result.Version != 1 {
		return Response{}, Code("worker_response_invalid")
	}
	if result.Code != "" {
		if !scanCodes[result.Code] || len(result.Response.Names) != 0 || len(result.Response.Candidates) != 0 || result.Response.Manifest != nil || result.Response.Location != nil || result.Response.Discovery != nil || result.Response.Accounts != nil {
			return Response{}, Code("worker_response_invalid")
		}
		return Response{}, result.Code
	}
	if request.Operation == "accounts" {
		if result.Response.Accounts == nil || !result.Response.Accounts.Validate() ||
			len(result.Response.Names) != 0 || len(result.Response.Candidates) != 0 || result.Response.Manifest != nil ||
			result.Response.Location != nil || result.Response.Discovery != nil {
			return Response{}, Code("worker_response_invalid")
		}
		return result.Response, nil
	}
	if result.Response.Accounts != nil {
		return Response{}, Code("worker_response_invalid")
	}
	if request.Operation == "discover" {
		if len(result.Response.Names) != 0 || len(result.Response.Candidates) != 0 || result.Response.Manifest != nil ||
			result.Response.Location != nil || result.Response.Discovery == nil || !result.Response.Discovery.Validate(request.Account != "") {
			return Response{}, Code("worker_response_invalid")
		}
		return result.Response, nil
	}
	if result.Response.Discovery != nil {
		return Response{}, Code("worker_response_invalid")
	}
	if request.Operation == "location" {
		if len(result.Response.Names) != 0 || len(result.Response.Candidates) != 0 || result.Response.Manifest != nil ||
			result.Response.Location == nil || !result.Response.Location.Validate(request.Account != "") {
			return Response{}, Code("worker_response_invalid")
		}
		return result.Response, nil
	}
	if result.Response.Location != nil {
		return Response{}, Code("worker_response_invalid")
	}
	if request.Operation == "manifest" {
		if len(result.Response.Names) != 0 || len(result.Response.Candidates) != 0 ||
			result.Response.Manifest == nil || !result.Response.Manifest.Validate() {
			return Response{}, Code("worker_response_invalid")
		}
	} else if request.Operation == "list" {
		if result.Response.Manifest != nil || len(result.Response.Candidates) != 0 || len(result.Response.Names) > presetfiles.MaxEntries {
			return Response{}, Code("worker_response_invalid")
		}
		for i, name := range result.Response.Names {
			if !boundedText(name, 255, false) || strings.ContainsAny(name, `/\:`) ||
				(i > 0 && name <= result.Response.Names[i-1]) {
				return Response{}, Code("worker_response_invalid")
			}
		}
	} else {
		if result.Response.Manifest != nil || len(result.Response.Names) != 0 || len(result.Response.Candidates) != len(request.Picks) {
			return Response{}, Code("worker_response_invalid")
		}
		for i, candidate := range result.Response.Candidates {
			digest, err := hex.DecodeString(candidate.Fingerprint)
			if candidate.Source.Name != request.Picks[i].Name || candidate.Source.Kind != request.Picks[i].Kind ||
				candidate.SchemaVersion != 1 || candidate.AdapterID != "bambu" || candidate.ParserVersion != printerpreset.ParserVersion ||
				err != nil || len(digest) != 32 {
				return Response{}, Code("worker_response_invalid")
			}
			if request.Operation == "select" && (candidate.Source.ApplicationVersion != "" ||
				!(presetfiles.BambuManifest{BundleVersion: candidate.Source.BundleVersion, Machines: []presetfiles.ManifestEntry{}}).Validate() ||
				(request.Account == "" && candidate.Source.Kind == printerpreset.User)) {
				return Response{}, Code("worker_response_invalid")
			}
		}
	}
	return result.Response, nil
}

// Serve handles one private request then exits. The bridge main does not call it
// yet. The parent owns the hard timeout; this child never launches other processes.
// The private pipe is transport, not authentication or consent by itself.
func Serve(input io.Reader, output io.Writer) int {
	data, err := io.ReadAll(io.LimitReader(input, MaxRequestBytes+1))
	result := envelope{Version: 1}
	var request wireRequest
	if err != nil || len(data) > MaxRequestBytes {
		result.Code = "worker_request_limit"
	} else if decode(data, &request) != nil || !validateRequest(request) {
		result.Code = "worker_request_invalid"
	} else {
		ctx, cancel := context.WithTimeout(context.Background(), printerpreset.MaxDuration)
		defer cancel()
		if request.Operation == "accounts" {
			result.Response.Accounts, err = presetfiles.ListBambuAccounts(ctx, request.Root)
		} else if request.Operation == "list" {
			result.Response.Names, err = presetfiles.ListJSON(ctx, request.Root)
		} else if request.Operation == "manifest" {
			result.Response.Manifest, err = presetfiles.ReadBambuManifest(ctx, request.Root)
		} else if request.Operation == "location" {
			result.Response.Location, err = presetfiles.InspectBambuLocation(ctx, request.Root, request.Account)
		} else if request.Operation == "discover" {
			result.Response.Discovery, err = presetfiles.DiscoverBambu(ctx, request.Root, request.Account)
		} else if request.Operation == "select" {
			result.Response.Candidates, err = presetfiles.SelectBambu(ctx, request.Root, request.Account, request.Picks)
		} else {
			inputs := make([]presetfiles.Input, len(request.Inputs))
			for i, input := range request.Inputs {
				inputs[i] = presetfiles.Input{Root: input.Root, Files: input.Files, Source: input.Source}
			}
			var catalog *printerpreset.Catalog
			catalog, err = presetfiles.LoadBambu(ctx, inputs)
			if err == nil {
				for _, pick := range request.Picks {
					var candidate printerpreset.Candidate
					candidate, err = catalog.Resolve(inputs[0].Source.Namespace, pick.Kind, pick.Name)
					if err != nil {
						break
					}
					result.Response.Candidates = append(result.Response.Candidates, candidate)
				}
			}
		}
		if err != nil {
			result.Response = Response{}
			result.Code = safeCode(err)
		}
	}
	data, err = json.Marshal(result)
	if err != nil || len(data) > MaxResponseBytes {
		data, _ = json.Marshal(envelope{Version: 1, Code: "worker_response_limit"})
	}
	if _, err := output.Write(data); err != nil {
		return 1
	}
	return 0
}
