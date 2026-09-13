//go:build darwin && (amd64 || arm64) && !makersvault_darwin_reader_experiment

package presetworker

import (
	"context"
	"testing"
)

// Native execution qualifies the existing unsupported response, not a macOS
// reader. Keep the successful filesystem round trips pending until one exists.
func TestDarwinWorkerRejectsUnimplementedReader(t *testing.T) {
	request := requestFixture(t)
	t.Setenv("MAKERSVAULT_PARENT_SECRET", "SYNTHETIC_SECRET")
	for _, input := range []Request{{Operation: "list", Root: request.Inputs[0].Root}, request} {
		response, err := Run(context.Background(), input)
		if err != Code("source_platform_unsupported") || len(response.Names) != 0 || len(response.Candidates) != 0 {
			t.Fatalf("unimplemented reader returned data or wrong status: %v %v", response, err)
		}
		waitIdle(t)
	}
}
