"""Pin the served OpenAPI document to checked-in fixtures, one file per schema domain.

Why the pin exists: Mf-avo9 split the single `schemas.py` module into a package of
per-domain modules behind a wildcard barrel. Nothing else in the suite would notice if
that split renamed a component, dropped a model or reordered a property: the routers
keep serving and the response models keep validating, because every consumer imports the
same classes the barrel re-exports. So the whole document is written out, one fixture per
domain module, and compared byte for byte.

The comparison is deliberately order-insensitive (`sort_keys=True`): FastAPI
alphabetises components and `paths` follows main.py's include order, which is itself a
serialised detail. Raw insertion order is not part of the contract; the set of surfaces
is.

The fixtures live inside the API build context (`makervault/api/tests/fixtures`), so
this module reads no repo-root path and never skips itself in the container. A missing
fixture is a hard failure, never a skip - the only permitted skip is the post-rewrite one
below.

Regenerating after an intentional contract change, from `makervault/api`:

    MAKERVAULT_WRITE_OPENAPI_FIXTURES=1 python -m pytest tests/test_openapi_contract.py

That rewrites the 15 files and then SKIPS, so a rewrite run can never report green; re-run
without the variable to verify. MAKERVAULT_WRITE_OPENAPI_FIXTURES must stay unset in the
Makefile and in CI, where a rewrite would pin whatever the code happened to emit.
"""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import main
import schemas

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "openapi"
COMPONENTS_DIR = FIXTURES / "components"
DOCUMENT_PATH = FIXTURES / "document.json"
PATHS_PATH = FIXTURES / "paths.json"

# The two components FastAPI itself contributes. They have no schemas module, so they
# live in document.json beside the other non-per-component surfaces.
BUILTIN_COMPONENTS = ("HTTPValidationError", "ValidationError")

# A bare `#/components/schemas/<Class>` is the only legal ref shape. A dotted name is how
# pydantic/FastAPI disambiguate two same-named models across modules, and that is exactly
# how a package split silently renames a component.
BARE_REF = re.compile(r"^#/components/schemas/[A-Za-z0-9_]+$")

REWRITE_ENV_VAR = "MAKERVAULT_WRITE_OPENAPI_FIXTURES"


def _canonical(document: dict[str, Any]) -> str:
    """Pretty-printed, key-sorted JSON with one trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        pytest.fail(f"missing OpenAPI fixture {path}; regenerate it with {REWRITE_ENV_VAR}=1")
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _domain_stems() -> dict[str, str]:
    """Map each domain module's `__name__` to the stem of its component fixture."""
    return {module.__name__: module.__name__.removeprefix("schemas.") for module in schemas.MODULES}


def _load() -> dict[str, Any]:
    """Reassemble the document from document.json, paths.json and every component file."""
    if not COMPONENTS_DIR.is_dir():
        pytest.fail(f"missing OpenAPI fixture directory {COMPONENTS_DIR}; regenerate it with {REWRITE_ENV_VAR}=1")

    document = _read_json(DOCUMENT_PATH)
    component_schemas: dict[str, Any] = dict(document["builtin_components"])
    for path in sorted(COMPONENTS_DIR.glob("*.json")):
        component_schemas.update(_read_json(path))

    return {
        "openapi": document["openapi"],
        "info": document["info"],
        "paths": _read_json(PATHS_PATH),
        "components": {
            "schemas": component_schemas,
            "securitySchemes": document["security_schemes"],
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical(payload), encoding="utf-8")


def _write(document: dict[str, Any]) -> None:
    """Rewrite the 15 fixtures, bucketing each component by its owning domain module.

    Iterating the OpenAPI components rather than `schemas.__all__` is deliberate:
    AssetCreate is dead code - exported by the barrel but routed nowhere - so it has no
    component. `__all__` would write a component that the document does not contain and
    then fail the comparison.
    """
    stems = _domain_stems()
    builtins: dict[str, Any] = {}
    by_domain: dict[str, dict[str, Any]] = {stem: {} for stem in stems.values()}

    for name, component in document["components"]["schemas"].items():
        model = getattr(schemas, name, None)
        if model is None:
            assert name in BUILTIN_COMPONENTS, (
                f"{name} is a component but neither a schemas export nor a FastAPI builtin; "
                "the barrel and the served document have diverged"
            )
            builtins[name] = component
            continue
        # A KeyError here is the loud unmapped-domain failure: a model whose __module__
        # is not in schemas.MODULES has no fixture file to live in.
        by_domain[stems[model.__module__]][name] = component

    _write_json(
        DOCUMENT_PATH,
        {
            "openapi": document["openapi"],
            "info": document["info"],
            "security_schemes": document["components"]["securitySchemes"],
            "builtin_components": builtins,
        },
    )
    _write_json(PATHS_PATH, document["paths"])
    for stem, components in by_domain.items():
        _write_json(COMPONENTS_DIR / f"{stem}.json", components)


def _iter_refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def test_the_document_matches_the_checked_in_fixtures() -> None:
    """The served document must equal the reassembled fixtures byte for byte.

    With MAKERVAULT_WRITE_OPENAPI_FIXTURES=1 the fixtures are rewritten and the test
    skips instead of passing, so a rewrite can never be mistaken for a verification.
    """
    document = main.app.openapi()

    if os.environ.get(REWRITE_ENV_VAR) == "1":
        _write(document)
        pytest.skip(f"fixtures rewritten; re-run without {REWRITE_ENV_VAR} to verify")

    assert _canonical(_load()) == _canonical(document)


def test_every_reference_names_a_bare_component() -> None:
    """No `$ref` anywhere may carry a dot, a slash or any other disambiguation."""
    refs = sorted(set(_iter_refs(main.app.openapi())))
    assert refs, "the served document contains no $ref at all"

    malformed = [ref for ref in refs if not BARE_REF.match(ref)]
    assert not malformed, (
        f"{len(malformed)} of {len(refs)} $ref(s) are not bare component names: {malformed}. "
        "Class names must stay globally unique inside the schemas package."
    )


def test_the_barrel_partitions_the_domain_modules() -> None:
    """`schemas.__all__` must be exactly the sorted union of its modules' `__all__`."""
    exported = schemas.__all__
    assert exported == sorted(exported), "the barrel's __all__ must stay sorted"
    assert len(exported) == len(set(exported)), "the barrel's __all__ repeats a name"

    for name in exported:
        owner = getattr(schemas, name).__module__
        assert owner.startswith("schemas."), f"{name} is exported from {owner}, not a schemas.* domain module"

    partition = sorted(name for module in schemas.MODULES for name in module.__all__)
    assert exported == partition, (
        "the barrel's __all__ is not the union of its modules' __all__: "
        f"only in the barrel {sorted(set(exported) - set(partition))}, "
        f"only in the modules {sorted(set(partition) - set(exported))}"
    )
