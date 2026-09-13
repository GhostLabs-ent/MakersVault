package printerpreset

import (
	"encoding/json"
	"math"
	"strconv"
	"strings"
)

const tolerance = 1e-8

func number(raw any) (float64, bool) {
	var text string
	switch value := raw.(type) {
	case string:
		text = value
	case json.Number:
		text = string(value)
	default:
		return 0, false
	}
	n, err := strconv.ParseFloat(text, 64)
	return n, err == nil && !math.IsNaN(n) && !math.IsInf(n, 0)
}

func points(raw any, maximum int) ([]Point, bool) {
	items, ok := raw.([]any)
	if !ok || len(items) > maximum {
		return nil, false
	}
	out := make([]Point, 0, len(items))
	for _, item := range items {
		text, ok := item.(string)
		if !ok {
			return nil, false
		}
		parts := strings.Split(text, "x")
		if len(parts) != 2 {
			return nil, false
		}
		x, xOK := number(parts[0])
		y, yOK := number(parts[1])
		if !xOK || !yOK || math.Abs(x) > 10000 || math.Abs(y) > 10000 {
			return nil, false
		}
		out = append(out, Point{x, y})
	}
	return out, true
}

func cross(a, b, c Point) float64 { return (b.X-a.X)*(c.Y-a.Y) - (b.Y-a.Y)*(c.X-a.X) }
func onSegment(a, b, p Point) bool {
	return math.Abs(cross(a, b, p)) <= tolerance && p.X >= math.Min(a.X, b.X)-tolerance && p.X <= math.Max(a.X, b.X)+tolerance && p.Y >= math.Min(a.Y, b.Y)-tolerance && p.Y <= math.Max(a.Y, b.Y)+tolerance
}
func intersect(a, b, c, d Point) bool {
	abC, abD, cdA, cdB := cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
	return (abC > tolerance && abD < -tolerance || abC < -tolerance && abD > tolerance) &&
		(cdA > tolerance && cdB < -tolerance || cdA < -tolerance && cdB > tolerance) ||
		onSegment(a, b, c) || onSegment(a, b, d) || onSegment(c, d, a) || onSegment(c, d, b)
}

func simple(p []Point) bool {
	if len(p) < 3 || len(p) > 256 {
		return false
	}
	area := 0.0
	for i, a := range p {
		b := p[(i+1)%len(p)]
		if math.Hypot(a.X-b.X, a.Y-b.Y) <= tolerance {
			return false
		}
		area += a.X*b.Y - b.X*a.Y
		// Adjacent collinear backtracking is invalid too.
		prev := p[(i+len(p)-1)%len(p)]
		if math.Abs(cross(prev, a, b)) <= tolerance && (prev.X-a.X)*(b.X-a.X)+(prev.Y-a.Y)*(b.Y-a.Y) > tolerance {
			return false
		}
		for j := i + 1; j < len(p); j++ {
			if j == i+1 || i == 0 && j == len(p)-1 {
				continue
			}
			if intersect(a, b, p[j], p[(j+1)%len(p)]) {
				return false
			}
		}
	}
	return math.Abs(area) > tolerance
}

func rectangle(p []Point) bool {
	if len(p) != 4 || !simple(p) {
		return false
	}
	for i, a := range p {
		b, c := p[(i+1)%4], p[(i+2)%4]
		if math.Abs((b.X-a.X)*(c.X-b.X)+(b.Y-a.Y)*(c.Y-b.Y)) > tolerance {
			return false
		}
	}
	return true
}

func provenance(v value, id key) string {
	if v.owner == id {
		return "source"
	}
	return "inherited"
}

func (out *Candidate) normalize(fields map[string]value, id key) {
	bedValue, exists := fields["printable_area"]
	bed, valid := points(bedValue.raw, 256)
	if len(bed) > 3 && bed[0] == bed[len(bed)-1] {
		bed = bed[:len(bed)-1]
	}
	if !exists || !valid || !simple(bed) {
		out.Reasons = append(out.Reasons, "invalid_or_missing_bed")
	} else {
		minX, minY, maxX, maxY := bed[0].X, bed[0].Y, bed[0].X, bed[0].Y
		for _, p := range bed {
			minX = math.Min(minX, p.X)
			minY = math.Min(minY, p.Y)
			maxX = math.Max(maxX, p.X)
			maxY = math.Max(maxY, p.Y)
		}
		if maxX-minX > 10000 || maxY-minY > 10000 {
			out.Reasons = append(out.Reasons, "bed_span_exceeded")
		} else {
			out.SourceOrigin = &Point{minX, minY}
			out.Bed = bed
			for i := range out.Bed {
				out.Bed[i].X -= minX
				out.Bed[i].Y -= minY
			}
			out.Provenance.Bed = provenance(bedValue, id)
		}
	}
	v, exists := fields["bed_exclude_area"]
	if !exists {
		out.Reasons = append(out.Reasons, "unknown_exclusions")
	} else {
		flat, valid := points(v.raw, 64)
		if !valid || len(flat)%4 != 0 {
			out.Reasons = append(out.Reasons, "invalid_exclusions")
		} else {
			polygons := make([][]Point, 0, len(flat)/4)
			for i := 0; i < len(flat); i += 4 {
				p := flat[i : i+4]
				if !rectangle(p) {
					valid = false
					break
				}
				polygons = append(polygons, p)
			}
			if !valid {
				out.Reasons = append(out.Reasons, "invalid_exclusions")
			} else if out.SourceOrigin != nil {
				for _, p := range polygons {
					for i := range p {
						p[i].X -= out.SourceOrigin.X
						p[i].Y -= out.SourceOrigin.Y
					}
				}
				out.Exclusions = polygons
				out.Provenance.Exclusions = provenance(v, id)
			}
		}
	}
	height := fields["printable_height"]
	n, valid := number(height.raw)
	if !valid || n <= 0 || n > 10000 {
		out.Reasons = append(out.Reasons, "invalid_or_missing_height")
	} else {
		out.Height = &n
		out.Provenance.Height = provenance(height, id)
	}
	nozzle := fields["nozzle_diameter"]
	items, ok := nozzle.raw.([]any)
	if !ok || len(items) != 1 {
		out.Reasons = append(out.Reasons, "invalid_or_multiple_nozzles")
	} else {
		n, valid := number(items[0])
		if !valid || n < 0.05 || n > 10 {
			out.Reasons = append(out.Reasons, "invalid_nozzle")
		} else {
			out.Nozzle = &n
			out.Provenance.Nozzle = provenance(nozzle, id)
		}
	}
}
