package presetfiles

import (
	"strings"
	"unicode"
)

// Pure syntax policy, exercised on every test host. Native volume/reparse checks
// are separate. No UNC, extended/device namespace, drive-relative or ADS spelling.
func windowsRootParts(name string) (string, []string, bool) {
	if len(name) < 4 || len(name) > 4096 || !safeText(name) || name[1:3] != `:\` ||
		!((name[0] >= 'A' && name[0] <= 'Z') || (name[0] >= 'a' && name[0] <= 'z')) {
		return "", nil, false
	}
	parts := strings.Split(name[3:], `\`)
	for _, part := range parts {
		if !componentName(part) {
			return "", nil, false
		}
	}
	return strings.ToUpper(name[:3]), parts, true
}

// A bounded Unicode simple-fold key (unlike ToLower, also joins sigma variants).
// This is a portability filter, not proof of all Windows filesystem case rules.
func foldName(name string) string {
	return strings.Map(func(r rune) rune {
		least := r
		for next := unicode.SimpleFold(r); next != r; next = unicode.SimpleFold(next) {
			if next < least {
				least = next
			}
		}
		return least
	}, name)
}
