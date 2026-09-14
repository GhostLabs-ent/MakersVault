package printerpreset

import (
	"bytes"
	"encoding/json"
	"io"
	"strings"
	"unicode/utf8"
)

var retained = map[string]bool{
	"type": true, "name": true, "from": true, "instantiation": true, "inherits": true,
	"printer_model": true, "printer_variant": true, "printer_technology": true,
	"printer_structure": true, "nozzle_diameter": true, "printable_area": true,
	"printable_height": true, "bed_exclude_area": true, "include": true,
	"extruder_printable_area": true, "extruder_printable_height": true,
	"printer_extruder_id": true, "physical_extruder_map": true,
	"schema_version": true, "format_version": true,
	"head_wrap_detect_zone": true, "wrapping_exclude_area": true,
}

func (c *Catalog) project(data []byte) (map[string]any, error) {
	if !utf8.Valid(data) {
		return nil, Code("invalid_json")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	nodes := 0
	value, err := c.jsonValue(decoder, true, 0, &nodes)
	if err != nil {
		return nil, err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return nil, Code("invalid_json")
	}
	fields, ok := value.(map[string]any)
	if !ok {
		return nil, Code("invalid_json")
	}
	return fields, nil
}

// Token walking checks duplicate keys even in discarded objects. Unknown values
// are validated but not retained; never marshal a raw vendor document for export.
func (c *Catalog) jsonValue(d *json.Decoder, keep bool, depth int, nodes *int) (any, error) {
	if err := c.check(); err != nil {
		return nil, err
	}
	*nodes++
	if depth > 32 || *nodes > 65536 {
		return nil, Code("json_budget_exceeded")
	}
	token, err := d.Token()
	if err != nil {
		return nil, Code("invalid_json")
	}
	delim, container := token.(json.Delim)
	if !container {
		if keep {
			if text, ok := token.(string); ok && !label(text, true) {
				return nil, Code("invalid_field")
			}
			return token, nil
		}
		return nil, nil
	}
	// Every retained vendor field is scalar or a flat array. Do not retain an
	// arbitrary nested object smuggled beneath an otherwise allowed field name.
	if keep && (depth > 0 && delim == '{' || depth > 1) {
		return nil, Code("invalid_field")
	}
	switch delim {
	case '{':
		var out map[string]any
		if keep {
			out = map[string]any{}
		}
		seen := map[string]bool{}
		for d.More() {
			keyToken, err := d.Token()
			key, ok := keyToken.(string)
			folded := strings.ToLower(key)
			if err != nil || !ok || !label(key, false) || seen[folded] {
				return nil, Code("invalid_json_key")
			}
			// Vendor header lookup is case-insensitive. Do not silently discard
			// aliases of identity/schema fields or accept disagreeing duplicates.
			for _, r := range key {
				if r > 127 {
					return nil, Code("invalid_json_key")
				}
			}
			if retained[folded] && key != folded {
				return nil, Code("invalid_json_key")
			}
			seen[folded] = true
			if len(seen) > 2048 {
				return nil, Code("json_budget_exceeded")
			}
			keepField := keep && (depth != 0 || retained[key])
			value, err := c.jsonValue(d, keepField, depth+1, nodes)
			if err != nil {
				return nil, err
			}
			if keepField {
				out[key] = value
			}
		}
		if end, err := d.Token(); err != nil || end != json.Delim('}') {
			return nil, Code("invalid_json")
		}
		return out, nil
	case '[':
		var out []any
		if keep {
			out = []any{}
		}
		count := 0
		for d.More() {
			count++
			if keep && count > 256 {
				return nil, Code("field_items_exceeded")
			}
			value, err := c.jsonValue(d, keep, depth+1, nodes)
			if err != nil {
				return nil, err
			}
			if keep {
				out = append(out, value)
			}
		}
		if end, err := d.Token(); err != nil || end != json.Delim(']') {
			return nil, Code("invalid_json")
		}
		return out, nil
	default:
		return nil, Code("invalid_json")
	}
}
