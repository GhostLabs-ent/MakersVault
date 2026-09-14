package presetfiles

import (
	"context"
	"fmt"
	"runtime"
	"strings"
	"testing"
)

func TestAccountChoicesValidation(t *testing.T) {
	for _, names := range [][]string{{}, {"default"}, {"A", "B", "private-account"}} {
		if !(AccountChoices{Names: names}).Validate() {
			t.Fatal("valid local choices rejected")
		}
	}
	for _, names := range [][]string{nil, {""}, {".."}, {"a/b"}, {"NUL"}, {" a"}, {"a."}, {"bad\nname"}, {"b", "a"}, {"A", "a"}, {"a", "a"}} {
		if (AccountChoices{Names: names}).Validate() {
			t.Fatal("invalid or ambiguous local choices accepted")
		}
	}
	names := make([]string, MaxEntries+1)
	for i := range names {
		names[i] = fmt.Sprintf("account-%05d", i)
	}
	if !(AccountChoices{Names: names[:MaxEntries]}).Validate() || (AccountChoices{Names: names}).Validate() {
		t.Fatal("account choice limit changed")
	}
}

func TestAccountsCancellationAndUnsupported(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if result, err := ListBambuAccounts(ctx, "/unused"); result != nil || err != Code("source_cancelled") {
		t.Fatal("cancelled listing proceeded")
	}
	if runtime.GOOS != "windows" && runtime.GOOS != "linux" {
		if result, err := ListBambuAccounts(context.Background(), "/unused"); result != nil || err != Code("source_platform_unsupported") {
			t.Fatal("deferred platform enabled")
		}
	}
}

func FuzzAccountChoices(f *testing.F) {
	for _, seed := range []string{"default", "A\x00a", "..", "NUL", "account\x00other", "", "one/two", "COM¹"} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, input string) {
		if len(input) > 4096 {
			return
		}
		names := strings.Split(input, "\x00")
		if (AccountChoices{Names: names}).Validate() {
			for i, name := range names {
				if !componentName(name) || (i > 0 && names[i-1] >= name) {
					t.Fatal("unsafe account choice")
				}
			}
		}
	})
}
