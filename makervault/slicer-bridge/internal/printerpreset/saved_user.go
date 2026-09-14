package printerpreset

import (
	"io"
	"strings"
)

// AddLocalUserMachine accepts a document ONLY from the locally selected Bambu
// user/<account>/machine directory. Its context is supplied by the confined
// adapter, never a document marker, filename heuristic, URL or private-wire mode.
// It does not itself grant filesystem/consent authority. Generic Add remains strict.
func (c *Catalog) AddLocalUserMachine(source Source, reader io.Reader) error {
	if source.Kind != User {
		c.failed = true
		return Code("invalid_source")
	}
	return c.add(source, "", reader, true)
}

func validateLocalUserMachine(fields map[string]any) error {
	from, ok := fields["from"].(string)
	if !ok || !strings.EqualFold(from, "user") {
		return Code("source_kind_mismatch")
	}
	if kind, explicit := fields["type"]; explicit && kind != "machine" {
		return Code("invalid_machine_identity")
	}
	version, ok := fields["version"].(string)
	if !ok || !savedUserVersion(version) {
		return Code("unsupported_user_version")
	}
	name, _ := fields["name"].(string)
	if strings.TrimSpace(name) != name || IsBambuScriptTemplate(name) {
		return Code("invalid_machine_identity")
	}
	return nil
}

// Conservative saved-file header grammar, not installed-version qualification or
// a comparison against the current application. Prerelease/build suffixes need
// separate fixtures; neither version nor missing geometry is inferred from it.
func savedUserVersion(version string) bool {
	parts := strings.Split(version, ".")
	if len(parts) != 3 && len(parts) != 4 {
		return false
	}
	for _, part := range parts {
		if len(part) == 0 || len(part) > 5 {
			return false
		}
		for _, r := range part {
			if r < '0' || r > '9' {
				return false
			}
		}
	}
	return true
}
