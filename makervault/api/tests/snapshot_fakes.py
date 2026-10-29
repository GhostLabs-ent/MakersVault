"""Scripted stand-ins for the two things the snapshot guard reaches outside itself.

The guard asks `storage_capabilities.detect()` whether the library volume can
snapshot, and it asks `snapshots.provider_for()` for the provider that would do
it. Both are module attributes, so a test patches the attribute and never the
function: these helpers exist so every test patches them the same way.

Two shapes, both documented below:

* `UNUSABLE` / `capability()` plus `use_unavailable()` / `use_capability()`
  answer the capability question with a fixed answer. `detect` is patched with a
  **no-positional-argument** lambda, which is exactly how the guard calls it, so
  a change to that call shape fails here instead of silently probing the host.
* `ScriptedProvider` is CephFS-shaped (one `mkdir` per snapshot, no copy), logs
  every `create` call and can be told to fail. `use_provider()` installs one and
  `use_tree_copy()` installs the local-copy double, which is the only provider
  that can prove a snapshot really holds the pre-delete bytes.

Nothing here creates the snapshot store on the guard's behalf: `<root>/.snap` is
materialised by `use_provider()` / `use_tree_copy()` themselves, because a
provider never creates it (`snapshots.NullProvider` explains why). Install the
fake first, then snapshot the tree.

Every helper takes a root the caller already monkeypatched into `db.STORAGE`, and
every root in the suite is a `tmp_path`: `LocalCopyProvider` copies the whole
root, so `tree_copy_provider()` must only ever see a tiny temporary tree, never a
real library.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

import snapshots
import storage_capabilities

# One volume with the library role and no snapshot method at all: the ext4 case.
UNUSABLE = storage_capabilities.VolumeCapability(
    roles=(storage_capabilities.LIBRARY_ROLE,),
    path="/library",
    fstype="ext",
    mount_point="/",
    snapshot_method=storage_capabilities.NO_METHOD,
    usable=False,
    reason="no snapshot method for ext",
)


def capability(
    method: str = storage_capabilities.CEPHFS_SNAPDIR,
    usable: bool = True,
    reason: str = "the .snap directory exists and is writable",
) -> storage_capabilities.VolumeCapability:
    """One library volume that reports ``method`` (usable unless told otherwise)."""
    return storage_capabilities.VolumeCapability(
        roles=(storage_capabilities.LIBRARY_ROLE,),
        path="/library",
        fstype="ceph",
        mount_point="/library",
        snapshot_method=method if usable else storage_capabilities.NO_METHOD,
        usable=usable,
        reason=reason,
    )


def use_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer `detect()` with `UNUSABLE`: the library volume cannot snapshot."""
    monkeypatch.setattr(storage_capabilities, "detect", lambda: [UNUSABLE])


def use_capability(monkeypatch: pytest.MonkeyPatch, **kwargs) -> storage_capabilities.VolumeCapability:
    """Answer `detect()` with `capability(**kwargs)` and return that volume."""
    volume = capability(**kwargs)
    monkeypatch.setattr(storage_capabilities, "detect", lambda: [volume])
    return volume


class ScriptedProvider(snapshots.CephFsSnapdirProvider):
    """CephFS-shaped: one mkdir per snapshot, no copy, logged, fail-injectable.

    `calls` records ``(reason, ctx)`` per `create`, which is how a test proves the
    guard took exactly one snapshot per request and handed the provider no audit
    context (a context would make the provider write its own rows). `fail` is
    raised *instead of* materialising anything, so the failure happens before a
    single byte is copied -- the same place a real missing `.snap` directory
    fails. On success the real `create` runs, so naming, containment and
    retention stay S2's code and this double cannot drift from them.
    """

    def __init__(
        self,
        root: Path,
        *,
        policy: Optional[snapshots.RetentionPolicy] = None,
        fail: Optional[BaseException] = None,
    ) -> None:
        # An explicit policy: a provider built from `retention_policy()` would
        # read the settings table, which no test here depends on.
        super().__init__(root, policy=policy or snapshots.RetentionPolicy())
        self.calls: list[tuple[snapshots.SnapshotReason, object]] = []
        self.fail = fail

    def create(
        self,
        reason: snapshots.SnapshotReason = snapshots.SnapshotReason.MANUAL,
        *,
        ctx=None,
    ) -> snapshots.SnapshotCreated:
        self.calls.append((reason, ctx))
        if self.fail is not None:
            raise self.fail
        return super().create(reason, ctx=ctx)


def _materialise_store(root: Path) -> Path:
    """Create `<root>/.snap`; the guard's provider never creates it itself."""
    store = Path(root) / snapshots.SNAPSHOT_DIRNAME
    store.mkdir(parents=True, exist_ok=True)
    return store


def use_provider(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    fail: Optional[BaseException] = None,
) -> ScriptedProvider:
    """Patch `provider_for` with one `ScriptedProvider` on `root`, and a usable volume.

    `root` must be the temporary root the caller already monkeypatched into
    `db.STORAGE`; the provider's containment checks resolve it.
    """
    _materialise_store(root)
    provider = ScriptedProvider(root, fail=fail)
    monkeypatch.setattr(snapshots, "provider_for", lambda *args, **kwargs: provider)
    use_capability(monkeypatch)
    return provider


def tree_copy_provider(root: Path) -> snapshots.LocalCopyProvider:
    """The local-copy double on `root`; only ever for a tiny `tmp_path` tree."""
    return snapshots.LocalCopyProvider(root, policy=snapshots.RetentionPolicy())


def use_tree_copy(monkeypatch: pytest.MonkeyPatch, root: Path) -> snapshots.LocalCopyProvider:
    """Patch `provider_for` with a `LocalCopyProvider` so a snapshot holds real bytes."""
    _materialise_store(root)
    provider = tree_copy_provider(root)
    monkeypatch.setattr(snapshots, "provider_for", lambda *args, **kwargs: provider)
    use_capability(monkeypatch, method=snapshots.LOCAL_COPY_METHOD)
    return provider
