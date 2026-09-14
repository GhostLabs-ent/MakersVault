//go:build linux && (amd64 || arm64)

package presetfiles

import (
	"context"
	"reflect"
	"testing"
)

func TestLinuxHintLookupIsNarrow(t *testing.T) {
	for _, config := range []string{"/synthetic/config", "", "relative", "/"} {
		var keys []string
		hints, err := linuxLocationHints(context.Background(), func(key string) string {
			keys = append(keys, key)
			if key == "XDG_CONFIG_HOME" {
				return config
			}
			if key == "HOME" {
				return "/synthetic/home"
			}
			t.Fatal("unrelated environment inspected")
			return ""
		})
		want := []string{"XDG_CONFIG_HOME"}
		if config == "" {
			want = append(want, "HOME")
		}
		if err != nil || !reflect.DeepEqual(keys, want) {
			t.Fatal("wrong hint lookup")
		}
		_, err = PlanBambuLocations(hints)
		if (config == "relative" || config == "/") != (err != nil) {
			t.Fatal("invalid XDG silently fell back")
		}
	}
}

func TestLinuxNativeHintsUseOnlySyntheticEnvironment(t *testing.T) {
	// Override XDG so the provider neither reads HOME nor touches real profiles.
	t.Setenv("XDG_CONFIG_HOME", "/synthetic/does-not-exist")
	choices, err := NativeBambuLocations(context.Background())
	if err != nil || len(choices) != 3 || choices[0].DataRoot != "/synthetic/does-not-exist/BambuStudio" {
		t.Fatal("native provider did filesystem discovery")
	}
}
