#!/usr/bin/env python3
"""Generate the deterministic, non-private Gate 2 preview benchmark corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def write_ascii_stl(path: Path) -> int:
    path.write_text(
        """solid tetrahedron
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 1 0 0
  vertex 0 1 0
 endloop
endfacet
facet normal 0 -1 0
 outer loop
  vertex 0 0 0
  vertex 0 0 1
  vertex 1 0 0
 endloop
endfacet
facet normal 1 1 1
 outer loop
  vertex 1 0 0
  vertex 0 0 1
  vertex 0 1 0
 endloop
endfacet
facet normal -1 0 0
 outer loop
  vertex 0 0 0
  vertex 0 1 0
  vertex 0 0 1
 endloop
endfacet
endsolid tetrahedron
""",
        encoding="ascii",
    )
    return 4


def write_binary_stl(path: Path, triangle_count: int) -> int:
    with path.open("wb") as handle:
        handle.write(b"MakersVault Gate 2 synthetic STL".ljust(80, b"\0"))
        handle.write(struct.pack("<I", triangle_count))
        for index in range(triangle_count):
            x = float(index % 1000)
            y = float((index // 1000) % 1000)
            z = float(index % 17) / 17.0
            handle.write(
                struct.pack(
                    "<12fH",
                    0.0,
                    0.0,
                    1.0,
                    x,
                    y,
                    z,
                    x + 0.75,
                    y,
                    z,
                    x,
                    y + 0.75,
                    z,
                    0,
                )
            )
    return triangle_count


def grid_side_for_triangles(target: int) -> int:
    return max(1, math.ceil(math.sqrt(target / 2)))


def write_obj(path: Path, target_triangles: int, parts: int) -> int:
    side = grid_side_for_triangles(target_triangles)
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("# MakersVault Gate 2 synthetic multipart OBJ\n")
        for y in range(side + 1):
            for x in range(side + 1):
                handle.write(f"v {x} {y} {(x + y) % 13 / 13:.5f}\n")
        faces_written = 0
        rows_per_part = max(1, math.ceil(side / parts))
        for y in range(side):
            if y % rows_per_part == 0:
                handle.write(f"o part_{min(parts - 1, y // rows_per_part):02d}\n")
            for x in range(side):
                a = y * (side + 1) + x + 1
                b = a + 1
                c = a + side + 1
                d = c + 1
                for face in ((a, b, d), (a, d, c)):
                    if faces_written >= target_triangles:
                        return faces_written
                    handle.write(f"f {face[0]} {face[1]} {face[2]}\n")
                    faces_written += 1
    return faces_written


def model_xml(target_triangles: int, object_id: int = 1) -> tuple[str, int]:
    side = grid_side_for_triangles(target_triangles)
    vertices: list[str] = []
    triangles: list[str] = []
    for y in range(side + 1):
        for x in range(side + 1):
            vertices.append(f'<vertex x="{x}" y="{y}" z="{(x + y) % 11 / 11:.5f}"/>')
    count = 0
    for y in range(side):
        for x in range(side):
            a = y * (side + 1) + x
            b = a + 1
            c = a + side + 1
            d = c + 1
            for face in ((a, b, d), (a, d, c)):
                if count >= target_triangles:
                    break
                triangles.append(f'<triangle v1="{face[0]}" v2="{face[1]}" v3="{face[2]}"/>')
                count += 1
            if count >= target_triangles:
                break
        if count >= target_triangles:
            break
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        '<resources>'
        f'<object id="{object_id}" type="model"><mesh><vertices>{"".join(vertices)}</vertices>'
        f'<triangles>{"".join(triangles)}</triangles></mesh></object>'
        '</resources>'
        f'<build><item objectid="{object_id}"/></build>'
        '</model>'
    )
    return xml, count


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def make_noise_png(width: int = 1536, height: int = 1536) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(((x * 17 + y * 31) & 255, (x * 47 + y * 13) & 255, (x * 7 + y * 61) & 255))
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), level=0))
        + png_chunk(b"IEND", b"")
    )


def write_3mf(path: Path, triangle_counts: list[int], thumbnail: bytes | None = None) -> int:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )
    total = 0
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types, compress_type=ZIP_DEFLATED)
        archive.writestr("_rels/.rels", rels, compress_type=ZIP_DEFLATED)
        for index, triangle_count in enumerate(triangle_counts):
            xml, actual = model_xml(triangle_count, object_id=index + 1)
            model_path = "3D/3dmodel.model" if index == 0 else f"3D/plate_{index + 1}.model"
            archive.writestr(model_path, xml, compress_type=ZIP_DEFLATED)
            total += actual
        if thumbnail is not None:
            archive.writestr("Metadata/thumbnail.png", thumbnail, compress_type=ZIP_STORED)
    return total


def record(path: Path, category: str, complexity: int | None, embedded_thumbnail: bool = False) -> dict[str, object]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "filename": path.name,
        "category": category,
        "bytes": path.stat().st_size,
        "complexity": complexity,
        "sha256": digest,
        "embedded_thumbnail": embedded_thumbnail,
    }


def generate(output: Path) -> list[dict[str, object]]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    entries: list[dict[str, object]] = []

    path = output / "01-small-ascii.stl"
    entries.append(record(path, "small", write_ascii_stl(path)))
    stl_specs = [
        ("02-small-binary.stl", 12, "small"),
        ("03-small-grid.stl", 1_000, "small"),
        ("04-small-detailed.stl", 5_000, "small"),
        ("05-medium-25k.stl", 25_000, "medium"),
        ("06-medium-50k.stl", 50_000, "medium"),
        ("07-medium-100k.stl", 100_000, "medium"),
        ("08-large-250k.stl", 250_000, "large"),
        ("09-large-500k.stl", 500_000, "large"),
    ]
    for filename, triangles, category in stl_specs:
        path = output / filename
        entries.append(record(path, category, write_binary_stl(path, triangles)))

    for filename, triangles, parts in [
        ("10-multipart-10k.obj", 10_000, 3),
        ("11-multipart-50k.obj", 50_000, 8),
        ("12-multipart-100k.obj", 100_000, 16),
    ]:
        path = output / filename
        entries.append(record(path, "multi-part", write_obj(path, triangles, parts)))

    thumbnail = make_noise_png()
    for filename, plates, category, with_image in [
        ("13-multibody-10k.3mf", [10_000], "multi-part", False),
        ("14-multiplate-50k.3mf", [20_000, 15_000, 15_000], "multi-plate", False),
        ("15-image-heavy-25k.3mf", [25_000], "image-heavy", True),
        ("16-multiplate-image-heavy.3mf", [15_000, 15_000, 15_000], "multi-plate-image-heavy", True),
    ]:
        path = output / filename
        complexity = write_3mf(path, plates, thumbnail if with_image else None)
        entries.append(record(path, category, complexity, with_image))

    malformed = {
        "17-malformed-truncated.stl": b"broken STL header\0\x01\x02",
        "18-malformed-archive.3mf": b"PK\x03\x04truncated synthetic archive",
        "19-malformed-mesh.obj": b"o broken\nv nope 0 0\nf 1 2 missing\n",
        "20-malformed-shape.step": b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('BROKEN'),'2;1');\nENDSEC;\n",
    }
    for filename, payload in malformed.items():
        path = output / filename
        path.write_bytes(payload)
        entries.append(record(path, "malformed", None))

    manifest = {
        "schema": 1,
        "generator": "generate_corpus.py",
        "fixture_count": len(entries),
        "total_bytes": sum(int(entry["bytes"]) for entry in entries),
        "fixtures": entries,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entries = generate(args.output.resolve())
    print(f"Generated {len(entries)} fixtures in {args.output.resolve()}")


if __name__ == "__main__":
    main()
