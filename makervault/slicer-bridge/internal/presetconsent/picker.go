package presetconsent

import (
	"context"
	"errors"
	"runtime"

	"makersvault/slicer-bridge/internal/presetfiles"
	"makersvault/slicer-bridge/internal/presetui"
)

type folderOperation struct {
	ctx    context.Context
	cancel context.CancelFunc
	done   chan struct{}
}

// startPicker requires the session lock and explicit local POST consent. The
// accepting HTTP request does not own a dialog's lifetime. No request paths,
// initial-directory hints, or filesystem reads are passed to this operation.
func (s *Session) startPicker() {
	ctx, cancel := context.WithTimeout(s.ctx, presetui.PickerTimeout)
	op := &folderOperation{ctx: ctx, cancel: cancel, done: make(chan struct{})}
	var previous []selection
	for _, id := range s.order {
		previous = append(previous, s.choices[id])
	}
	s.clear()
	s.picker, s.busy, s.stage, s.revision = op, true, "picking", token()
	go s.finishPicker(op, previous)
}

func (s *Session) finishPicker(op *folderOperation, previous []selection) {
	defer close(op.done)
	defer op.cancel()
	root, err := s.backend.pick(op.ctx)
	if err == nil {
		_, err = presetfiles.PlanBambuLocations(presetfiles.LocationHints{Platform: runtime.GOOS, CustomDataRoot: root})
		// An empty custom path means default hints to the planner, not a choice.
		if root == "" {
			err = Code("consent_source_invalid")
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.picker != op {
		return
	}
	s.picker, s.busy = nil, false // never free the slot before the callback returns
	if !s.live() {
		return // owner close/expiry wins even over a late successful result
	}
	s.stage, s.revision = "roots", token()
	s.offer(previous) // old forms/IDs cannot reuse the interrupted root selection
	switch {
	case errors.Is(op.ctx.Err(), context.DeadlineExceeded), errors.Is(err, presetui.Code("ui_timeout")):
		s.warning = "Folder selection timed out. No presets were read. Choose a folder again or cancel."
	case op.ctx.Err() != nil, errors.Is(err, presetui.Code("ui_cancelled")):
		s.warning = "Folder selection cancelled. No presets were read."
	case err != nil:
		s.warning = "Folder selection is unavailable or the selection is unsupported. No presets were read. Choose a folder again or cancel."
	default:
		// Keep the chosen path in local session memory only, never in HTML/form
		// fields. A separate opaque-ID confirmation is required before reading.
		s.offer([]selection{{label: "Folder selected on this workstation (existence unverified)", root: root}})
	}
}
