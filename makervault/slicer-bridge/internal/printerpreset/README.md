# Bambu review projection — MP-1a

This internal package has no filesystem discovery, network, command or persistence
code, and is **not yet called by the bridge executable**. It consumes documents
supplied by a future consented, bounded local reader. No automatic workstation scan
or new public bridge command is enabled by adding this package.

`NewBambu(ctx)` creates one serial catalog operation. `Add(source, reader)` projects
one already-authorized machine document. `Resolve(namespace, kind, exactName)` returns
a typed review candidate or a redacted reason code. A failed Add invalidates the
catalog, so callers cannot quietly offer a truncated scan as complete. Catalog
construction is not concurrency-safe; finish one operation before sharing results.

MP-1b-5 adds `AddIndexed` (bind manifest name before retaining a document),
`ReadIndex` (charge index bytes/files to the same budget) and `Selections` (validate
all loaded parent chains and list only explicit true instantiation). Parser version
`bambu-projection-2` additionally rejects malformed instantiation, case-aliased
headers/duplicates and non-ASCII keys. Original projection fingerprints therefore
carry a different parser version; old evidence is historical, not requalified.
See the [content adapter's limits](../presetfiles/DISCOVERY.md), especially ordinary
saved-user files without explicit machine headers, which are not supported yet.

The source namespace and discarded settings do not enter the candidate or its
fingerprint. Source labels may still contain user-authored private text: the later
import review must show what will be shared. Version strings are supplied observations,
not proof of a supported application build. The fingerprint hashes Go's deterministic
JSON projection with the fingerprint field omitted; cross-language wire validation
and golden encodings are required before the API import contract is implemented.

`Complete()` means the **projected layout fields** are present and valid under this
parser's rules. It is not a trusted validator for caller-mutated structs, a verified
snapshot, an owned/online printer, a compatible output, or a print-safety certificate.
The future API must independently validate submitted metadata.

## Supported projection and limits

- Exact namespace/name inheritance; system profiles cannot inherit user profiles.
  Ambiguous user/system parents fail instead of guessing precedence. Hidden/missing
  instantiation is not assumed selectable. Actual user-profile discovery and vendor
  precedence compatibility remain to be qualified.
- FFF/corexy, i3 or delta descriptions; one nozzle; one distinct tool identity.
  Unsupported multiple-tool, per-tool or auxiliary wrapping geometry is explicit.
- Simple bed polygons, including centered/concave shapes, retain their vertices.
  XY is translated to the bed minima and the original offset is retained.
- Bambu exclusions are groups of four rectangle vertices, not one long polygon.
  Empty is distinct from absent. Nonrectangular exclusions are unsupported by this
  adapter; the later normalized contract can represent other polygons.
- Recognized G-code-template include names are never opened or executed; other
  include forms fail. Credential, account, URL, arbitrary notes, image/path and
  script fields are discarded. No raw vendor document is serialized as output.
- 10,000 documents, 8 MiB/document, 128 MiB total; 16 inheritance levels, 15 seconds
  per catalog operation. JSON depth 32, 65,536 value tokens, 2,048 keys/object and
  256 items/retained array; duplicate keys and invalid UTF-8 fail. Only known flat
  field shapes are retained; an explicit unknown source schema marker fails.
- Labels/retained strings are bounded to 200 Unicode characters without controls.
  Coordinates must lie within ±10,000 mm and spans/heights within 10,000 mm; nozzle
  range 0.05–10 mm. The geometry tolerance is 1e-8; this conservative parser check
  is not the forthcoming packing/collision solver.

Read one bounded document at a time. Cancellation is checked between Reader calls
and JSON tokens; it does **not** interrupt an arbitrarily blocked Reader. The future
OS boundary must reject special files and escape paths and bound its I/O separately.
No `os.Root`/symlink/reparse-point or native Windows filesystem qualification is
claimed by pure projection tests. These limits do not change model-upload limits.

The synthetic fixtures and tests cover normalization, privacy, geometry, error and
budget boundaries. Named public source references are recorded in the
[fixture inventory](../../../docs/evidence/gate-13/MAKE_PLATE_FIXTURES.md).
No test asserts support for all Bambu profiles or the owner's reported `v2.8.0.6`.
