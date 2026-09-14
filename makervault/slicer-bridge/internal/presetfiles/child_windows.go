//go:build windows && (amd64 || arm64)

package presetfiles

import "context"

func (d *directory) child(ctx context.Context, name string) (*directory, error) {
	if err := check(ctx); err != nil {
		return nil, err
	}
	if !componentName(name) {
		return nil, Code("source_path_invalid")
	}
	if _, err := validateHandle(d.file, true, d.volume); err != nil {
		return nil, err
	}
	file, err := openRelative(d.file, name, true)
	if err != nil {
		return nil, err
	}
	if _, err := validateHandle(file, true, d.volume); err != nil {
		file.Close()
		return nil, err
	}
	if err := check(ctx); err != nil {
		file.Close()
		return nil, err
	}
	return &directory{file: file, volume: d.volume}, nil
}
