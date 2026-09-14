// Package presetconsent is an inactive local preview/consent foundation. It has
// no remote import, persistence, browser launch or production-main integration.
package presetconsent

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/url"
	"runtime"
	"strings"
	"sync"
	"time"

	"makersvault/slicer-bridge/internal/presetfiles"
	"makersvault/slicer-bridge/internal/presetworker"
	"makersvault/slicer-bridge/internal/printerpreset"
)

const MaxLifetime = 5 * time.Minute

type Code string

func (c Code) Error() string { return string(c) }

// Config is constructed locally after future protocol validation. CustomRoot is
// supplied by a native local configuration/picker, never an HTTP form or server.
// Origin is display binding only: this package does not authenticate a remote claim.
type Config struct {
	Origin     string    `json:"-"`
	ExpiresAt  time.Time `json:"-"`
	CustomRoot string    `json:"-"`
}

type Choice struct{ ID, Label string }
type View struct {
	Origin, Stage, Warning, Revision, Digest, Preview string
	Choices                                           []Choice
	Busy                                              bool
}

// Action accepts only ephemeral local choice IDs and the currently displayed
// revision/digest, never filesystem paths, account names or raw preset JSON.
type Action struct {
	Revision, Decision, Digest string
	Choices                    []string
}

type backend struct {
	hints func(context.Context) ([]presetfiles.BambuLocation, error)
	run   func(context.Context, presetworker.Request) (presetworker.Response, error)
}
type selection struct {
	label, root, account string
	pick                 printerpreset.Selection
}

type Session struct {
	mu                                                   sync.Mutex
	ctx                                                  context.Context
	cancel                                               context.CancelFunc
	origin, customRoot, stage, warning, revision, digest string
	choices                                              map[string]selection
	order                                                []string
	root, account                                        string
	preview                                              []byte
	busy                                                 bool
	serverStarted                                        bool
	backend                                              backend
}

func token() string {
	var bytes [32]byte
	// Go's crypto/rand.Read fails irrecoverably if system entropy is unavailable.
	_, _ = rand.Read(bytes[:])
	return hex.EncodeToString(bytes[:])
}

func New(ctx context.Context, config Config) (*Session, error) {
	return newSession(ctx, config, backend{presetworker.NativeLocations, presetworker.Run})
}

func newSession(ctx context.Context, config Config, runner backend) (*Session, error) {
	u, err := url.Parse(config.Origin)
	if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.Path != "" ||
		u.RawQuery != "" || u.ForceQuery || strings.HasSuffix(u.Host, ":") || u.Fragment != "" || u.Opaque != "" || len(config.Origin) > 2048 ||
		u.String() != config.Origin || strings.ToLower(u.Host) != u.Host ||
		config.ExpiresAt.IsZero() || !config.ExpiresAt.After(time.Now()) ||
		config.ExpiresAt.After(time.Now().Add(MaxLifetime)) || runner.hints == nil || runner.run == nil {
		return nil, Code("consent_configuration_invalid")
	}
	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		return nil, Code("source_platform_unsupported")
	}
	if config.CustomRoot != "" {
		if _, err := presetfiles.PlanBambuLocations(presetfiles.LocationHints{Platform: runtime.GOOS, CustomDataRoot: config.CustomRoot}); err != nil {
			return nil, Code("consent_configuration_invalid")
		}
	}
	ctx, cancel := context.WithDeadline(ctx, config.ExpiresAt)
	s := &Session{ctx: ctx, cancel: cancel, origin: config.Origin, customRoot: config.CustomRoot,
		stage: "consent", revision: token(), backend: runner}
	return s, nil
}

func (s *Session) clear() {
	s.choices, s.order, s.preview = nil, nil, nil
	s.root, s.account, s.digest, s.warning = "", "", "", ""
}

func (s *Session) live() bool {
	if s.ctx.Err() != nil {
		s.clear()
		s.customRoot = ""
		if s.stage == "consumed" {
			return false
		}
		if s.ctx.Err() == context.DeadlineExceeded {
			s.stage = "expired"
		} else {
			s.stage = "cancelled"
		}
		return false
	}
	return s.stage != "cancelled" && s.stage != "expired" && s.stage != "consumed"
}

// Close revokes consent even during in-flight work; no later worker result can
// resurrect choices or approval. Call when the local UI/session owner goes away.
func (s *Session) Close() {
	s.cancel()
	s.mu.Lock()
	defer s.mu.Unlock()
	s.live()
}

func (s *Session) View() View {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.live()
	v := View{Origin: s.origin, Stage: s.stage, Warning: s.warning, Revision: s.revision,
		Digest: s.digest, Preview: string(s.preview), Busy: s.busy}
	for _, id := range s.order {
		v.Choices = append(v.Choices, Choice{id, s.choices[id].label})
	}
	return v
}

func (s *Session) offer(items []selection) {
	s.choices, s.order = map[string]selection{}, nil
	for _, item := range items {
		id := token()
		s.choices[id] = item
		s.order = append(s.order, id)
	}
}

// Apply serializes transitions but releases the lock during bounded worker I/O,
// so cancellation/expiry and UI inspection can proceed. One revision is consumed
// before work starts; replays/stale tabs cannot launch another scan or approve it.
func (s *Session) Apply(ctx context.Context, action Action) error {
	s.mu.Lock()
	if !s.live() {
		s.mu.Unlock()
		return Code("consent_closed")
	}
	if action.Decision == "cancel" && len(action.Choices) == 0 && action.Digest == "" {
		s.cancel()
		s.live()
		s.mu.Unlock()
		return nil
	}
	if s.busy {
		s.mu.Unlock()
		return Code("consent_busy")
	}
	if action.Revision != s.revision {
		s.mu.Unlock()
		return Code("consent_stale")
	}
	if action.Decision == "restart" && len(action.Choices) == 0 && action.Digest == "" {
		s.clear()
		s.stage = "consent"
		s.revision = token()
		s.mu.Unlock()
		return nil
	}
	stage := s.stage
	valid := action.Digest == ""
	var chosen selection
	var picks []printerpreset.Selection
	switch stage {
	case "consent":
		valid = valid && action.Decision == "allow" && len(action.Choices) == 0
	case "roots", "accounts":
		valid = valid && action.Decision == "choose" && len(action.Choices) == 1
		if valid {
			var ok bool
			chosen, ok = s.choices[action.Choices[0]]
			valid = ok
		}
	case "presets":
		valid = valid && action.Decision == "preview" && len(action.Choices) > 0 && len(action.Choices) <= presetfiles.MaxSelected
		seen := map[string]bool{}
		if valid {
			for _, id := range action.Choices {
				item, ok := s.choices[id]
				if !ok || seen[id] {
					valid = false
					break
				}
				seen[id] = true
				picks = append(picks, item.pick)
			}
		}
	case "review":
		valid = action.Decision == "approve" && len(action.Choices) == 0 && action.Digest != "" && action.Digest == s.digest
	default:
		valid = false
	}
	if !valid {
		s.mu.Unlock()
		return Code("consent_action_invalid")
	}
	if ctx.Err() != nil {
		s.mu.Unlock()
		return Code("consent_operation_cancelled")
	}
	s.revision = token()
	if stage == "review" {
		s.stage = "approved"
		s.mu.Unlock()
		return nil
	}
	s.busy = true
	root, account, custom := s.root, s.account, s.customRoot
	if stage == "roots" {
		root = chosen.root
	}
	if stage == "accounts" {
		account = chosen.account
	}
	s.mu.Unlock()

	work, cancel := context.WithTimeout(s.ctx, printerpreset.MaxDuration)
	stop := context.AfterFunc(ctx, cancel)
	defer stop()
	defer cancel()
	var items []selection
	var preview []byte
	var warning, next string
	var err error
	switch stage {
	case "consent":
		var locations []presetfiles.BambuLocation
		if custom != "" {
			locations, err = presetfiles.PlanBambuLocations(presetfiles.LocationHints{Platform: runtime.GOOS, CustomDataRoot: custom})
		} else {
			locations, err = s.backend.hints(work)
		}
		if err == nil {
			if len(locations) == 0 || len(locations) > 3 {
				err = Code("consent_source_invalid")
			}
			for _, location := range locations {
				if _, e := presetfiles.PlanBambuLocations(presetfiles.LocationHints{Platform: runtime.GOOS, CustomDataRoot: location.DataRoot}); e != nil {
					err = Code("consent_source_invalid")
					break
				}
				items = append(items, selection{label: location.ID + " — " + location.DataRoot, root: location.DataRoot})
			}
		}
		next = "roots"
	case "roots":
		var response presetworker.Response
		response, err = s.backend.run(work, presetworker.Request{Operation: "accounts", Root: root})
		items = []selection{{label: "System presets only (do not read account presets)"}}
		if err != nil {
			warning = "Account folders could not be listed. Restart to retry, or explicitly choose system presets only."
			err = nil // an explicit system-only choice is offered, never selected
		} else if response.Accounts == nil || !response.Accounts.Validate() {
			err = Code("consent_source_invalid")
		} else {
			for _, name := range response.Accounts.Names {
				items = append(items, selection{label: name, account: name})
			}
		}
		next = "accounts"
	case "accounts":
		var response presetworker.Response
		response, err = s.backend.run(work, presetworker.Request{Operation: "discover", Root: root, Account: account})
		if err == nil {
			if response.Discovery == nil || !response.Discovery.Validate(account != "") {
				err = Code("consent_source_invalid")
			} else {
				for _, pick := range response.Discovery.Selections {
					items = append(items, selection{label: string(pick.Kind) + " — " + pick.Name, pick: pick})
				}
			}
		}
		next = "presets"
	case "presets":
		var response presetworker.Response
		response, err = s.backend.run(work, presetworker.Request{Operation: "select", Root: root, Account: account, Picks: picks})
		if err == nil {
			if len(response.Candidates) != len(picks) {
				err = Code("consent_source_invalid")
			} else {
				for i, candidate := range response.Candidates {
					if candidate.Source.Name != picks[i].Name || candidate.Source.Kind != picks[i].Kind {
						err = Code("consent_source_invalid")
						break
					}
				}
			}
			if err == nil {
				preview, err = json.Marshal(response.Candidates)
			}
			if len(preview) > presetworker.MaxResponseBytes {
				err = Code("consent_preview_limit")
			}
		}
		next = "review"
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.busy = false
	if !s.live() {
		return Code("consent_closed")
	}
	if work.Err() != nil || ctx.Err() != nil {
		err = Code("consent_operation_cancelled")
	}
	if err != nil {
		s.clear()
		s.stage = "failed"
		s.warning = "The local operation failed or exceeded its limits. Nothing was approved. Restart to retry."
		return Code("consent_source_failed") // never expose raw backend diagnostics
	}
	s.stage, s.root, s.account, s.warning, s.preview = next, root, account, warning, preview
	s.offer(items)
	if next == "review" {
		digest := sha256.Sum256(preview)
		s.digest = hex.EncodeToString(digest[:])
	}
	return nil
}

// TakeApproved returns the exact reviewed bytes once, never account/root data.
// This is LOCAL approval only, not authority to claim/submit/commit remotely.
// Future integration must separately verify remote approval, expiry and trust.
func (s *Session) TakeApproved() ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.live() || s.stage != "approved" {
		return nil, Code("consent_not_approved")
	}
	result := append([]byte(nil), s.preview...)
	s.clear()
	s.customRoot = ""
	s.stage = "consumed"
	s.cancel() // release an attached local host after exact one-use consumption
	return result, nil
}
