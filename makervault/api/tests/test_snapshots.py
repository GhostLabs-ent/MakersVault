"""Snapshot providers and retention, against synthesised trees under ``tmp_path``.

Every snapshot here is a real directory in a temporary root: the CephFS provider
is exercised against a plain ``tmp_path/.snap`` (where ``rmdir`` behaves the same
way and the "can never remove a real tree" guarantee is directly observable),
and the round trip runs through ``LocalCopyProvider``, which is the CI test
double and needs no snapshottable filesystem. No test names ``/mnt/ceph``, reads
the real storage root, or touches the live deployment; the one test that needs a
real mount lives in ``test_snapshots_integration.py`` behind ``SNAPSHOT_INTEGRATION``.

Audit rows are looked up by their target, never deleted: the table is
append-only. The four retention settings are restored by an autouse fixture, so
a policy written here cannot leak into the next test module.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import pytest
from sqlmodel import Session, select

import audit
import db
import snapshots
import storage_capabilities
from db import engine
from migrations import run_migrations
from models import AppConfig, AuditEvent

CTX = audit.AuditContext(
    actor=audit.Actor("tester", "admin", "user", None),
    request_id="req-snapshots",
    method="POST",
    path="/snapshots",
)

DAY = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
FROZEN = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)

RETENTION_KEYS = (
    snapshots.RETENTION_KEEP_LAST_N_KEY,
    snapshots.RETENTION_KEEP_DAILY_KEY,
    snapshots.RETENTION_MAX_AGE_DAYS_KEY,
    snapshots.RETENTION_HARD_CAP_KEY,
)


# --- helpers ----------------------------------------------------------------


def days_after(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=timezone.utc) + timedelta(days=day)


def snapshot_at(created: datetime, suffix: str = "000001", reason: snapshots.SnapshotReason = snapshots.SnapshotReason.MANUAL) -> str:
    """A name exactly as a provider would have written it at ``created``."""
    return snapshots.snapshot_name(reason, created, suffix=suffix)


def tree_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    return root


def local_copy(root: Path, policy: Optional[snapshots.RetentionPolicy] = None) -> snapshots.LocalCopyProvider:
    """The CI double, with an explicitly created ``.snap``: nothing creates it for us."""
    (root / snapshots.SNAPSHOT_DIRNAME).mkdir(exist_ok=True)
    return snapshots.LocalCopyProvider(root, policy=policy or snapshots.RetentionPolicy())


def audit_rows(target: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.target == target)))


def store_setting(key: str, value: str) -> None:
    with Session(engine) as session:
        row = session.get(AppConfig, key)
        if row is None:
            session.add(AppConfig(key=key, value=value))
        else:
            row.value = value
        session.commit()


def setting_value(key: str) -> Optional[str]:
    with Session(engine) as session:
        row = session.get(AppConfig, key)
        return row.value if row is not None else None


@pytest.fixture(autouse=True)
def database():
    """Migrated database, and the four retention rows this module may change put back."""
    run_migrations(engine)
    with Session(engine) as session:
        previous = {}
        for key in RETENTION_KEYS:
            row = session.get(AppConfig, key)
            previous[key] = row.value if row is not None else None
    yield
    with Session(engine) as session:
        for key, value in previous.items():
            row = session.get(AppConfig, key)
            if value is None:
                if row is not None:
                    session.delete(row)
            elif row is not None:
                row.value = value
            else:
                session.add(AppConfig(key=key, value=value))
        session.commit()


def step_clock(monkeypatch: pytest.MonkeyPatch, start: datetime, seconds: int = 60) -> None:
    """Advance ``snapshots._now`` by ``seconds`` on every call, from ``start``."""
    calls: list[int] = []

    def clock() -> datetime:
        calls.append(1)
        return start + timedelta(seconds=seconds * (len(calls) - 1))

    monkeypatch.setattr(snapshots, "_now", clock)


# --- AC-3: names carry their creation time --------------------------------


@pytest.mark.parametrize("reason", list(snapshots.SnapshotReason))
def test_ac3_a_generated_name_parses_back_to_the_snapshot_it_describes(reason: snapshots.SnapshotReason) -> None:
    now = FROZEN
    name = snapshots.snapshot_name(reason, now)

    parsed = snapshots.parse_name(name)

    assert parsed == snapshots.Snapshot(name=name, created_at=now, reason=reason)
    assert snapshots.NAME_RE.fullmatch(name)
    assert parsed.created_at.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "junk",
    [
        "x",
        "../../etc",
        ".snap",
        "20260101T000000Z-manual",
        "20260101T000000Z-manual-abcdef0",
        "20260101T000000Z-MANUAL-abcdef",
        "20260101T000000Z-manual-ABCDEF",
        "20260101T000000Z-manual-abcde",
        "2026010XT000000Z-manual-abcdef",
        "",
        ".",
        "..",
    ],
)
def test_ac3_a_name_this_module_did_not_write_parses_as_none(junk: str) -> None:
    assert snapshots.parse_name(junk) is None


def test_ac3_a_name_with_an_unknown_reason_parses_as_none() -> None:
    assert snapshots.parse_name("20260101T000000Z-teatime-abcdef") is None


def test_ac3_lexicographic_order_is_creation_order_across_a_date_boundary() -> None:
    before = snapshots.snapshot_name(snapshots.SnapshotReason.MANUAL, datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc))
    after = snapshots.snapshot_name(snapshots.SnapshotReason.MANUAL, datetime(2026, 2, 1, 0, 0, 1, tzinfo=timezone.utc))

    assert before < after
    assert snapshots.parse_name(before).created_at < snapshots.parse_name(after).created_at


def test_ac3_fifty_names_at_one_frozen_second_are_unique_and_all_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    monkeypatch.setattr(snapshots, "_now", lambda: frozen)

    names = [snapshots.snapshot_name(snapshots.SnapshotReason.SCHEDULED, snapshots._now()) for _ in range(50)]

    assert len(set(names)) == 50
    for name in names:
        assert snapshots.NAME_RE.fullmatch(name)
        assert snapshots.parse_name(name).created_at == frozen


# --- AC-2: retention -------------------------------------------------------


def retention_cases() -> list:
    """plan_prune cases: every rule, and every rule beating the one before it."""
    cases = []

    old = snapshot_at(days_after(0))
    fresh = snapshot_at(days_after(39), "000002")
    cases.append(
        pytest.param(
            [old, fresh],
            snapshots.RetentionPolicy(keep_last_n=10, keep_daily=0, max_age_days=30, hard_cap=100),
            days_after(40),
            (),
            [(old, snapshots.RULE_MAX_AGE)],
            [fresh],
            id="max_age",
        )
    )

    five = [snapshot_at(days_after(10 + index), f"00000{index + 1}") for index in range(5)]
    cases.append(
        pytest.param(
            five,
            snapshots.RetentionPolicy(keep_last_n=2, keep_daily=0, max_age_days=3650, hard_cap=100),
            days_after(20),
            (),
            [(name, snapshots.RULE_KEEP) for name in five[:3]],
            [five[4], five[3]],
            id="keep_last_n",
        )
    )
    cases.append(
        pytest.param(
            five,
            snapshots.RetentionPolicy(keep_last_n=5, keep_daily=0, max_age_days=3650, hard_cap=2),
            days_after(20),
            (),
            [(name, snapshots.RULE_HARD_CAP) for name in five[:3]],
            [five[4], five[3]],
            id="hard_cap_beats_keep",
        )
    )

    first, second, third = (snapshot_at(days_after(index), f"00000{index + 1}") for index in range(3))
    cases.append(
        pytest.param(
            [first, second, third],
            snapshots.RetentionPolicy(keep_last_n=10, keep_daily=0, max_age_days=1, hard_cap=100),
            days_after(2),
            (),
            [(first, snapshots.RULE_MAX_AGE)],
            [third, second],
            id="age_beats_keep",
        )
    )

    per_day = [snapshot_at(days_after(10 + index // 2, 10 if index % 2 == 0 else 20), f"00000{index + 1}") for index in range(6)]
    cases.append(
        pytest.param(
            per_day,
            snapshots.RetentionPolicy(keep_last_n=1, keep_daily=2, max_age_days=3650, hard_cap=100),
            days_after(20),
            (),
            [
                (per_day[0], snapshots.RULE_KEEP),
                (per_day[1], snapshots.RULE_KEEP),
                (per_day[2], snapshots.RULE_KEEP),
                (per_day[4], snapshots.RULE_KEEP),
            ],
            [per_day[5], per_day[3]],
            id="keep_daily_protects_one_per_day",
        )
    )

    aged = snapshot_at(days_after(0))
    newer = snapshot_at(days_after(1), "000002")
    cases.append(
        pytest.param(
            [aged, newer],
            snapshots.RetentionPolicy(keep_last_n=5, keep_daily=0, max_age_days=1, hard_cap=5),
            days_after(2),
            (aged,),
            [],
            [newer, aged],
            id="protect_is_exempt_from_every_rule",
        )
    )
    cases.append(
        pytest.param(
            [first, second, third],
            snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=3650, hard_cap=1),
            days_after(20),
            (first, second, third),
            [],
            [third, second, first],
            id="a_protected_set_larger_than_the_cap_is_an_accepted_overflow",
        )
    )

    valid = snapshot_at(days_after(0))
    cases.append(
        pytest.param(
            ["junk", ".snap", "20260101T000000Z-MANUAL-abcdef", valid, "notes.txt", ""],
            snapshots.RetentionPolicy(keep_last_n=5, keep_daily=0, max_age_days=3650, hard_cap=100),
            days_after(0),
            (),
            [],
            [valid],
            id="unparsable_names_are_never_pruned_or_kept",
        )
    )
    return cases


@pytest.mark.parametrize("names,policy,now,protect,pruned,kept", retention_cases())
def test_ac2_plan_prune_pins_both_the_pruned_names_and_the_rule(
    names: list[str],
    policy: snapshots.RetentionPolicy,
    now: datetime,
    protect: Iterable[str],
    pruned: list[tuple[str, str]],
    kept: list[str],
) -> None:
    plan = snapshots.plan_prune(names, policy, now=now, protect=protect)

    assert [(decision.name, decision.rule) for decision in plan.prune] == pruned
    assert list(plan.keep) == kept
    assert plan.pruned == len(pruned)
    assert plan.kept == len(kept)


def test_ac2_fifty_snapshots_today_under_the_default_policy_leave_twenty() -> None:
    """The worked example in ``plan_prune``'s docstring, executed."""
    names = [snapshot_at(FROZEN - timedelta(seconds=index), f"{index:06x}") for index in range(50)]

    plan = snapshots.plan_prune(names, snapshots.RetentionPolicy(), now=FROZEN)

    assert plan.kept == 20
    assert plan.pruned == 30
    assert all(decision.rule == snapshots.RULE_KEEP for decision in plan.prune)
    assert list(plan.keep) == names[:20]


def test_ac2_plan_prune_never_reads_the_clock_when_now_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> datetime:
        raise AssertionError("plan_prune read the clock with an explicit now")

    monkeypatch.setattr(snapshots, "_now", forbidden)

    plan = snapshots.plan_prune([snapshot_at(days_after(0))], snapshots.RetentionPolicy(), now=days_after(1))

    assert plan.kept == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("keep_last_n", 0),
        ("keep_last_n", True),
        ("keep_daily", -1),
        ("max_age_days", 0),
        ("hard_cap", 0),
        ("hard_cap", "10"),
    ],
)
def test_a_policy_that_cannot_be_honoured_names_the_field_and_the_value(field: str, value: object) -> None:
    with pytest.raises(ValueError) as caught:
        snapshots.RetentionPolicy(**{field: value})

    assert field in str(caught.value)
    assert repr(value) in str(caught.value)


# --- AC-2: retention runs on create ---------------------------------------


def test_ac2_the_just_created_snapshot_is_never_pruned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    policy = snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=1, hard_cap=1)
    provider = local_copy(root, policy)
    old = snapshot_at(FROZEN - timedelta(days=10), "0000aa")
    (provider.snapshot_dir / old).mkdir()
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    created = provider.create()

    assert [snapshot.name for snapshot in provider.list()] == [created.snapshot.name]
    assert created.snapshot.name not in [decision.name for decision in created.prune.prune]
    assert [(decision.name, decision.rule) for decision in created.prune.prune] == [(old, snapshots.RULE_MAX_AGE)]
    assert not (provider.snapshot_dir / old).exists()


def test_ac2_creating_beyond_the_cap_lands_exactly_on_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    policy = snapshots.RetentionPolicy(keep_last_n=100, keep_daily=7, max_age_days=3650, hard_cap=3)
    provider = local_copy(root, policy)
    step_clock(monkeypatch, FROZEN)

    plans = [provider.create(snapshots.SnapshotReason.SCHEDULED) for _ in range(5)]

    assert len(provider.list()) == 3
    assert [plan.prune.pruned for plan in plans] == [0, 0, 0, 1, 1]
    assert all(decision.rule == snapshots.RULE_HARD_CAP for decision in plans[-1].prune.prune)
    assert plans[-1].snapshot.name == max(snapshot.name for snapshot in provider.list())


def test_one_create_reads_the_clock_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The name's instant is also the retention reference: one create, one reading."""
    provider = local_copy(tree_root(tmp_path))
    readings: list[datetime] = []

    def clock() -> datetime:
        readings.append(FROZEN + timedelta(seconds=len(readings) + 1))
        return readings[-1]

    monkeypatch.setattr(snapshots, "_now", clock)

    created = provider.create()

    assert len(readings) == 1
    assert created.snapshot.created_at == readings[0].replace(microsecond=0)


def test_ac2_retention_prunes_through_the_cephfs_provider_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    (root / snapshots.SNAPSHOT_DIRNAME).mkdir()
    policy = snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=3650, hard_cap=1)
    provider = snapshots.CephFsSnapdirProvider(root, policy=policy)
    step_clock(monkeypatch, FROZEN)

    created = [provider.create() for _ in range(3)]

    assert [snapshot.name for snapshot in provider.list()] == [created[-1].snapshot.name]
    assert [decision.name for decision in created[-1].prune.prune] == [created[1].snapshot.name]


# --- AC-1: round trip through the local-copy double -----------------------


def test_ac1_a_snapshot_round_trips_through_the_local_copy_double(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    (root / "sub").mkdir()
    (root / "top.stl").write_bytes(b"solid cube\nendsolid cube\n")
    (root / "sub" / "file.bin").write_bytes(bytes(range(256)))
    (root / "sub" / "modèle-éà.bin").write_bytes(b"\x00\xffbinary\x00")
    provider = local_copy(root)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    created = provider.create(snapshots.SnapshotReason.MANUAL)

    listed = provider.list()
    assert len(listed) == 1
    assert listed[0] == snapshots.Snapshot(name=created.snapshot.name, created_at=FROZEN, reason=snapshots.SnapshotReason.MANUAL)
    assert provider.path_for(created.snapshot.name, "top.stl").read_bytes() == (root / "top.stl").read_bytes()
    assert provider.path_for(created.snapshot.name, "sub/file.bin").read_bytes() == bytes(range(256))
    assert provider.path_for(created.snapshot.name, "sub/modèle-éà.bin").read_bytes() == b"\x00\xffbinary\x00"
    assert provider.path_for(created.snapshot.name) == (root / snapshots.SNAPSHOT_DIRNAME / created.snapshot.name).resolve()
    assert not (provider.path_for(created.snapshot.name) / snapshots.SNAPSHOT_DIRNAME).exists()

    provider.delete(created.snapshot.name)

    assert provider.list() == []
    assert not (root / snapshots.SNAPSHOT_DIRNAME / created.snapshot.name).exists()


def test_ac1_the_copy_is_byte_identical_and_keeps_mtimes(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root / "model.stl").write_bytes(b"solid model\n")
    os.utime(root / "model.stl", (1_700_000_000, 1_700_000_000))
    provider = local_copy(root)

    created = provider.create()
    copied = provider.path_for(created.snapshot.name, "model.stl")

    assert copied.read_bytes() == (root / "model.stl").read_bytes()
    assert copied.stat().st_mtime == (root / "model.stl").stat().st_mtime


def test_a_nested_snapshot_root_is_not_copied_into_its_own_copy(tmp_path: Path) -> None:
    """A store below the root must not be walked into the copy it is holding."""
    root = tree_root(tmp_path)
    (root / "models").mkdir()
    (root / "models" / "model.stl").write_bytes(b"solid model\n")
    store = root / "a" / "b"
    store.mkdir(parents=True)
    provider = snapshots.LocalCopyProvider(root, policy=snapshots.RetentionPolicy(), snapshot_root=store)

    created = provider.create()

    copied = provider.path_for(created.snapshot.name)
    assert (copied / "models" / "model.stl").read_bytes() == b"solid model\n"
    assert not (copied / "a" / "b").exists()
    assert [snapshot.name for snapshot in provider.list()] == [created.snapshot.name]


def test_ac1_a_delete_that_finds_nothing_is_a_not_found(tmp_path: Path) -> None:
    provider = local_copy(tree_root(tmp_path))
    missing = snapshot_at(FROZEN, "00beef")

    with pytest.raises(snapshots.SnapshotNotFound):
        provider.delete(missing)


# --- AC-4: containment on the source and the destination ------------------


@pytest.mark.parametrize(
    "relative",
    ["..", "../outside", "thumbs", "bundles/x", ".trash", ".incoming", ".snap", "THUMBS/x", ".Snap/model.stl"],
)
def test_ac4_a_library_path_must_stay_inside_the_root_and_outside_reserved_trees(tmp_path: Path, relative: str) -> None:
    root = tree_root(tmp_path)

    with pytest.raises(snapshots.SnapshotPathError):
        snapshots.assert_library_path(relative, root=root)


@pytest.mark.parametrize("relative", ["/etc/passwd", str(Path("/tmp"))])
def test_ac4_an_absolute_library_path_is_refused(tmp_path: Path, relative: str) -> None:
    with pytest.raises(snapshots.SnapshotPathError):
        snapshots.assert_library_path(relative, root=tree_root(tmp_path))


def test_ac4_a_symlink_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    os.symlink(outside, root / "link")

    with pytest.raises(snapshots.SnapshotPathError):
        snapshots.assert_library_path("link/secret.txt", root=root)


def test_ac4_a_library_path_equal_to_the_root_is_refused(tmp_path: Path) -> None:
    root = tree_root(tmp_path)

    with pytest.raises(snapshots.SnapshotPathError):
        snapshots.assert_library_path("", root=root)


def test_ac4_a_snapshot_path_inside_the_view_resolves(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root / "sub").mkdir()
    (root / "sub" / "file.bin").write_bytes(b"bytes")
    provider = local_copy(root)
    created = provider.create()

    assert provider.path_for(created.snapshot.name, "sub/file.bin").read_bytes() == b"bytes"
    assert provider.path_for(created.snapshot.name, "sub/../sub/file.bin").name == "file.bin"


@pytest.mark.parametrize(
    "relpath",
    ["..", "../other", "thumbs", "bundles/x", ".trash", ".incoming", ".snap", "THUMBS/x", "/etc/passwd"],
)
def test_ac4_a_snapshot_path_must_stay_inside_the_snapshot(tmp_path: Path, relpath: str) -> None:
    provider = local_copy(tree_root(tmp_path))
    created = provider.create()

    with pytest.raises(snapshots.SnapshotPathError):
        provider.path_for(created.snapshot.name, relpath)


def test_ac4_a_symlink_inside_a_snapshot_that_points_out_is_refused(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    provider = local_copy(root)
    created = provider.create()
    os.symlink(outside, provider.snapshot_dir / created.snapshot.name / "escape")

    with pytest.raises(snapshots.SnapshotPathError):
        provider.path_for(created.snapshot.name, "escape/secret.txt")


def test_a_symlinked_snapshot_directory_outside_the_store_is_refused(tmp_path: Path) -> None:
    """``.snap/<name>`` as a symlink out of the root must not become a view root."""
    provider = local_copy(tree_root(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    planted = snapshot_at(FROZEN, "00aa11")
    os.symlink(outside, provider.snapshot_dir / planted)

    with pytest.raises(snapshots.SnapshotPathError):
        provider.path_for(planted, "secret.txt")
    with pytest.raises(snapshots.SnapshotPathError):
        provider.path_for(planted)


def test_delete_refuses_a_symlinked_snapshot_directory_and_leaves_the_target(tmp_path: Path) -> None:
    provider = local_copy(tree_root(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    planted = snapshot_at(FROZEN, "00aa11")
    os.symlink(outside, provider.snapshot_dir / planted)

    with pytest.raises(snapshots.SnapshotPathError):
        provider.delete(planted)

    assert (outside / "secret.txt").read_bytes() == b"secret"


def test_a_sibling_symlink_in_the_store_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A link to a sibling snapshot must not be served under its own name, nor deleted through."""
    root = tree_root(tmp_path)
    (root / "model.stl").write_bytes(b"solid model\n")
    provider = local_copy(root)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)
    real = provider.create()
    real_dir = provider.snapshot_dir / real.snapshot.name
    sibling = snapshot_at(FROZEN, "00b0b0")
    link = provider.snapshot_dir / sibling
    os.symlink(real_dir, link)

    with pytest.raises(snapshots.SnapshotPathError) as caught_root:
        provider.path_for(sibling)
    with pytest.raises(snapshots.SnapshotPathError):
        provider.path_for(sibling, "model.stl")
    with pytest.raises(snapshots.SnapshotPathError):
        provider.delete(sibling)

    assert str(link) in str(caught_root.value)
    assert (real_dir / "model.stl").read_bytes() == b"solid model\n"
    assert link.is_symlink()


def test_a_planted_symlink_never_wedges_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retention comes from ``list``, which excludes symlinks, so ``create`` never hits the refusal."""
    root = tree_root(tmp_path)
    policy = snapshots.RetentionPolicy(keep_last_n=10, keep_daily=0, max_age_days=1, hard_cap=10)
    provider = local_copy(root, policy)
    real = snapshot_at(FROZEN - timedelta(hours=1), "0000aa")
    (provider.snapshot_dir / real).mkdir()
    # Old enough to be an age prune if ``list`` counted it: the wedge this guards.
    planted = snapshot_at(FROZEN - timedelta(days=10), "00b0b0")
    os.symlink(provider.snapshot_dir / real, provider.snapshot_dir / planted)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    created = provider.create()

    assert [snapshot.name for snapshot in provider.list()] == [real, created.snapshot.name]
    assert (provider.snapshot_dir / real).is_dir()
    assert (provider.snapshot_dir / planted).is_symlink()
    assert created.prune.pruned == 0


def test_path_for_a_missing_snapshot_is_not_found(tmp_path: Path) -> None:
    provider = local_copy(tree_root(tmp_path))
    missing = snapshot_at(FROZEN, "00beef")

    with pytest.raises(snapshots.SnapshotNotFound):
        provider.path_for(missing)
    with pytest.raises(snapshots.SnapshotNotFound):
        provider.path_for(missing, "model.stl")


def test_path_for_with_no_snapshot_directory_is_not_found(tmp_path: Path) -> None:
    """Browsing a volume whose ``.snap`` is absent asks for a missing snapshot."""
    root = tree_root(tmp_path)
    provider = snapshots.LocalCopyProvider(root, policy=snapshots.RetentionPolicy())

    with pytest.raises(snapshots.SnapshotNotFound):
        provider.path_for(snapshot_at(FROZEN, "00beef"))


def test_path_for_returns_the_snapshot_directory_and_resolves_inside_it(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root / "sub").mkdir()
    (root / "sub" / "file.bin").write_bytes(b"bytes")
    provider = local_copy(root)
    created = provider.create()

    assert provider.path_for(created.snapshot.name) == (provider.snapshot_dir / created.snapshot.name).resolve()
    assert provider.path_for(created.snapshot.name).is_dir()
    assert provider.path_for(created.snapshot.name, "sub/file.bin").read_bytes() == b"bytes"


def test_list_ignores_a_regular_file_and_a_symlink_with_a_snapshot_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only directories are snapshots: a planted file or symlink cannot wedge create()."""
    root = tree_root(tmp_path)
    (root / snapshots.SNAPSHOT_DIRNAME).mkdir()
    policy = snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=3650, hard_cap=1)
    provider = snapshots.CephFsSnapdirProvider(root, policy=policy)
    planted_file = snapshot_at(FROZEN - timedelta(days=10), "0000f1")
    planted_link = snapshot_at(FROZEN - timedelta(days=10), "0000f2")
    (provider.snapshot_dir / planted_file).write_bytes(b"not a snapshot")
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, provider.snapshot_dir / planted_link)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    assert provider.list() == []

    created = provider.create()

    assert [snapshot.name for snapshot in provider.list()] == [created.snapshot.name]
    assert (provider.snapshot_dir / planted_file).read_bytes() == b"not a snapshot"
    assert (provider.snapshot_dir / planted_link).is_symlink()
    assert outside.is_dir()


@pytest.mark.parametrize("name", ["../../x", "", "nonsense", ".snap", "20260101T000000Z-MANUAL-abcdef", "/etc"])
def test_ac4_delete_refuses_a_name_that_is_not_a_snapshot_of_ours(tmp_path: Path, name: str) -> None:
    provider = local_copy(tree_root(tmp_path))

    with pytest.raises(snapshots.SnapshotPathError):
        provider.delete(name)


@pytest.mark.parametrize(
    "name",
    ["../../x", "", "nonsense", ".snap"],
)
def test_ac4_path_for_refuses_a_name_that_is_not_a_snapshot_of_ours(tmp_path: Path, name: str) -> None:
    provider = local_copy(tree_root(tmp_path))

    with pytest.raises(snapshots.SnapshotPathError):
        provider.path_for(name)


def test_ac4_a_snapshot_directory_outside_the_root_is_refused_at_construction(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(snapshots.SnapshotPathError):
        snapshots.CephFsSnapdirProvider(root, policy=snapshots.RetentionPolicy(), snapshot_root=outside)
    with pytest.raises(snapshots.SnapshotPathError):
        snapshots.LocalCopyProvider(root, policy=snapshots.RetentionPolicy(), snapshot_root=root)


def test_a_snapshot_directory_inside_the_root_is_accepted(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    store = root / "snapshots"
    store.mkdir()

    provider = snapshots.LocalCopyProvider(root, policy=snapshots.RetentionPolicy(), snapshot_root=store)

    assert provider.snapshot_dir == store.resolve()


# --- the CephFS provider --------------------------------------------------


def test_cephfs_never_creates_the_snap_directory_implicitly(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    provider = snapshots.CephFsSnapdirProvider(root, policy=snapshots.RetentionPolicy())

    with pytest.raises(snapshots.SnapshotUnavailable) as caught:
        provider.create()

    assert str(provider.snapshot_dir) in str(caught.value)
    assert not (root / snapshots.SNAPSHOT_DIRNAME).exists()
    assert provider.list() == []


def test_cephfs_create_list_and_delete_use_the_snap_directory(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root / snapshots.SNAPSHOT_DIRNAME).mkdir()
    provider = snapshots.CephFsSnapdirProvider(root, policy=snapshots.RetentionPolicy())

    created = provider.create(snapshots.SnapshotReason.SCHEDULED)

    target = root / snapshots.SNAPSHOT_DIRNAME / created.snapshot.name
    assert target.is_dir()
    assert [snapshot.name for snapshot in provider.list()] == [created.snapshot.name]
    assert provider.list()[0].reason == snapshots.SnapshotReason.SCHEDULED
    assert provider.path_for(created.snapshot.name) == target.resolve()

    provider.delete(created.snapshot.name)

    assert not target.exists()
    assert provider.list() == []


def test_cephfs_rmdir_can_never_remove_a_real_tree(tmp_path: Path) -> None:
    """On a non-CephFS volume ``.snap`` is a plain directory; ``rmdir`` refuses a tree."""
    root = tree_root(tmp_path)
    (root / snapshots.SNAPSHOT_DIRNAME).mkdir()
    provider = snapshots.CephFsSnapdirProvider(root, policy=snapshots.RetentionPolicy())
    created = provider.create()
    target = root / snapshots.SNAPSHOT_DIRNAME / created.snapshot.name
    (target / "a-real-file.stl").write_bytes(b"solid tree\n")

    with pytest.raises(snapshots.SnapshotError) as caught:
        provider.delete(created.snapshot.name)

    assert not isinstance(caught.value, snapshots.SnapshotPathError)
    assert str(target) in str(caught.value)
    assert (target / "a-real-file.stl").read_bytes() == b"solid tree\n"
    assert [snapshot.name for snapshot in provider.list()] == [created.snapshot.name]


def test_cephfs_delete_of_a_missing_snapshot_is_not_found(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root / snapshots.SNAPSHOT_DIRNAME).mkdir()
    provider = snapshots.CephFsSnapdirProvider(root, policy=snapshots.RetentionPolicy())

    with pytest.raises(snapshots.SnapshotNotFound):
        provider.delete(snapshot_at(FROZEN, "00beef"))


def test_cephfs_a_directory_it_did_not_write_is_invisible_and_immune(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root / snapshots.SNAPSHOT_DIRNAME / "not-ours").mkdir(parents=True)
    provider = snapshots.CephFsSnapdirProvider(
        root, policy=snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=1, hard_cap=1)
    )

    created = provider.create()

    assert (root / snapshots.SNAPSHOT_DIRNAME / "not-ours").is_dir()
    assert [snapshot.name for snapshot in provider.list()] == [created.snapshot.name]


# --- provider_for and the null provider -----------------------------------


@pytest.mark.parametrize(
    "method,expected",
    [
        (storage_capabilities.CEPHFS_SNAPDIR, snapshots.CephFsSnapdirProvider),
        (snapshots.LOCAL_COPY_METHOD, snapshots.LocalCopyProvider),
        (storage_capabilities.NO_METHOD, snapshots.NullProvider),
        (storage_capabilities.ZFS_DATASET, snapshots.NullProvider),
        (storage_capabilities.BTRFS_SUBVOL, snapshots.NullProvider),
        ("nonsense", snapshots.NullProvider),
        ("", snapshots.NullProvider),
    ],
)
def test_provider_for_maps_the_method_and_never_raises(tmp_path: Path, method: str, expected: type) -> None:
    provider = snapshots.provider_for(tree_root(tmp_path), method, policy=snapshots.RetentionPolicy())

    assert type(provider) is expected


def test_provider_for_names_the_providers_it_can_browse(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    cephfs = snapshots.provider_for(root, storage_capabilities.CEPHFS_SNAPDIR, policy=snapshots.RetentionPolicy())
    local = snapshots.provider_for(root, snapshots.LOCAL_COPY_METHOD, policy=snapshots.RetentionPolicy())
    null = snapshots.provider_for(root, storage_capabilities.NO_METHOD, policy=snapshots.RetentionPolicy())

    assert (cephfs.supports_browse, cephfs.supports_restore) == (True, True)
    assert (local.supports_browse, local.supports_restore) == (True, True)
    assert (null.supports_browse, null.supports_restore) == (False, False)
    assert null.list() == []


def test_the_null_provider_refuses_create_delete_and_browse(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    provider = snapshots.NullProvider(root, policy=snapshots.RetentionPolicy())

    for operation in (
        lambda: provider.create(),
        lambda: provider.delete(snapshot_at(FROZEN, "000001")),
        lambda: provider.path_for(snapshot_at(FROZEN, "000001")),
    ):
        with pytest.raises(snapshots.SnapshotUnavailable) as caught:
            operation()
        assert storage_capabilities.NO_METHOD in str(caught.value)
        assert str(root.resolve()) in str(caught.value)


def test_library_root_is_read_at_call_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "STORAGE", tmp_path)

    assert snapshots.library_root() == tmp_path
    assert snapshots.provider_for().root == tmp_path.resolve()
    assert isinstance(snapshots.provider_for(), snapshots.NullProvider)


# --- audit -----------------------------------------------------------------


def test_audit_create_and_delete_write_a_row_per_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = local_copy(tree_root(tmp_path))
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    created = provider.create(snapshots.SnapshotReason.MANUAL, ctx=CTX)
    name = created.snapshot.name
    provider.delete(name, ctx=CTX)

    rows = [row for row in audit_rows(name) if row.request_id == CTX.request_id]
    create_rows = [row for row in rows if row.action == audit.SNAPSHOT_CREATE]
    delete_rows = [row for row in rows if row.action == audit.SNAPSHOT_DELETE]
    assert len(create_rows) == 1
    assert len(delete_rows) == 1
    assert json.loads(create_rows[0].detail_json) == {"method": snapshots.LOCAL_COPY_METHOD, "pruned": 0, "reason": "manual"}
    assert json.loads(delete_rows[0].detail_json) == {"method": snapshots.LOCAL_COPY_METHOD}
    assert create_rows[0].actor == "tester"
    assert create_rows[0].method == "POST"
    assert create_rows[0].path == "/snapshots"
    assert delete_rows[0].target == name


def test_audit_one_prune_row_names_the_rule_and_the_triggering_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    policy = snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=1, hard_cap=1)
    provider = local_copy(root, policy)
    old = snapshot_at(FROZEN - timedelta(days=10), "0000aa")
    (provider.snapshot_dir / old).mkdir()
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    created = provider.create(ctx=CTX)

    prune_rows = [row for row in audit_rows(old) if row.action == audit.SNAPSHOT_PRUNE]
    assert len(prune_rows) == 1
    assert json.loads(prune_rows[0].detail_json) == {"rule": snapshots.RULE_MAX_AGE, "trigger": created.snapshot.name}
    create_rows = [row for row in audit_rows(created.snapshot.name) if row.action == audit.SNAPSHOT_CREATE]
    assert json.loads(create_rows[0].detail_json)["pruned"] == 1


def test_audit_a_none_context_writes_nothing_and_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = local_copy(tree_root(tmp_path))
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    created = provider.create()
    provider.delete(created.snapshot.name)

    assert audit_rows(created.snapshot.name) == []
    assert provider.list() == []


def test_audit_the_snapshot_actions_are_declared_and_on_no_route() -> None:
    for action in (audit.SNAPSHOT_CREATE, audit.SNAPSHOT_PRUNE, audit.SNAPSHOT_DELETE):
        assert action in audit.ACTIONS
        assert all(action not in actions for actions in audit.ROUTE_ACTIONS.values())
    assert len(audit.ACTIONS) == 24
    assert len(audit.ROUTE_ACTIONS) == 21
    assert audit.assert_audit_coverage() == audit.ROUTE_ACTIONS


# --- docs pins ------------------------------------------------------------


def test_audit_docs_describe_the_snapshot_actions() -> None:
    path = Path(__file__).resolve().parents[3] / "docs" / "AUDIT.md"
    # The API image build context is makervault/api, so docs/ is absent there.
    # This must be a function-level skip, not a module-level one: the other tests in
    # this module still have to run inside the image.
    if not path.exists():
        pytest.skip("host-only: docs is outside the API image build context")

    text = path.read_text(encoding="utf-8")
    assert "exactly these 24 strings" in text
    for needle in ("snapshot.create", "snapshot.prune", "snapshot.delete"):
        assert needle in text
    # The prose is hard-wrapped, so the sentence is pinned with its whitespace
    # normalised: the words are byte-for-byte, the wrap points are not.
    assert (
        "The matrix has 65 routes, 25 of them `GET`; the remaining 40 split into 21 audited keys and 19 exempt keys."
        in " ".join(text.split())
    )
    assert "fail-loud" in text


def test_configuration_docs_describe_the_retention_settings() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "CONFIGURATION.md"
    # Function-level for the same reason as the test above.
    if not path.exists():
        pytest.skip("host-only: makervault/docs is outside the API image build context")

    text = path.read_text(encoding="utf-8")
    for needle in (
        "snapshot_keep_last_n",
        "snapshot_keep_daily",
        "snapshot_max_age_days",
        "snapshot_hard_cap",
        "## Storage snapshot capabilities",
        "GET /storage/capabilities",
        "0x00C36400",
        ".snap",
        "zfs",
        "btrfs",
        "No snapshot is taken in this slice.",
    ):
        assert needle in text
    # The retention paragraph must say which key may be zero, and that a refused
    # stored value is an error, not a default: ``snapshot_keep_daily`` accepts 0.
    assert "`snapshot_keep_daily` is non-negative" in text
    assert "the other three keys are positive" in text
    assert "a refused stored value is an error rather than a silently replaced default" in " ".join(text.split())


def test_development_docs_describe_the_snapshot_integration_opt_in() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "DEVELOPMENT.md"
    # Function-level for the same reason as the tests above.
    if not path.exists():
        pytest.skip("host-only: makervault/docs is outside the API image build context")

    text = path.read_text(encoding="utf-8")
    assert "SNAPSHOT_INTEGRATION=1" in text
    assert "SNAPSHOT_INTEGRATION_ROOT" in text
    # The recipe must create the scratch root: the module skips when it is absent,
    # so a pasted block without ``mkdir -p`` produces a skip, not evidence.
    assert 'mkdir -p "$scratch"' in text
    assert "at least three path components deep" in " ".join(text.split())


# --- retention settings ---------------------------------------------------


def test_retention_defaults_come_from_an_empty_configuration() -> None:
    for key in RETENTION_KEYS:
        assert setting_value(key) is None

    assert snapshots.retention_policy() == snapshots.RetentionPolicy()
    assert snapshots.retention_policy() == snapshots.RetentionPolicy(keep_last_n=20, keep_daily=7, max_age_days=30, hard_cap=100)


@pytest.mark.parametrize(
    "key,field",
    [
        (snapshots.RETENTION_KEEP_LAST_N_KEY, "keep_last_n"),
        (snapshots.RETENTION_KEEP_DAILY_KEY, "keep_daily"),
        (snapshots.RETENTION_MAX_AGE_DAYS_KEY, "max_age_days"),
        (snapshots.RETENTION_HARD_CAP_KEY, "hard_cap"),
    ],
)
def test_a_stored_retention_key_overrides_its_default(key: str, field: str) -> None:
    store_setting(key, "3")

    policy = snapshots.retention_policy()

    assert getattr(policy, field) == 3
    for other in {"keep_last_n", "keep_daily", "max_age_days", "hard_cap"} - {field}:
        assert getattr(policy, other) == getattr(snapshots.RetentionPolicy(), other)


def test_a_blank_retention_row_falls_back_to_the_default() -> None:
    store_setting(snapshots.RETENTION_KEEP_DAILY_KEY, "   ")

    assert snapshots.retention_policy().keep_daily == snapshots.DEFAULT_KEEP_DAILY


def test_a_retention_row_that_is_not_an_integer_fails_loud() -> None:
    store_setting(snapshots.RETENTION_KEEP_LAST_N_KEY, "many")

    with pytest.raises(ValueError) as caught:
        snapshots.retention_policy()

    assert str(caught.value) == "the setting snapshot_keep_last_n is not an integer"


def test_a_stored_zero_is_validated_rather_than_silently_defaulted() -> None:
    store_setting(snapshots.RETENTION_KEEP_LAST_N_KEY, "0")

    with pytest.raises(ValueError) as caught:
        snapshots.retention_policy()

    assert "keep_last_n" in str(caught.value)


def test_set_retention_policy_writes_all_four_keys_and_round_trips() -> None:
    policy = snapshots.RetentionPolicy(keep_last_n=3, keep_daily=2, max_age_days=11, hard_cap=9)

    snapshots.set_retention_policy(policy)

    assert setting_value(snapshots.RETENTION_KEEP_LAST_N_KEY) == "3"
    assert setting_value(snapshots.RETENTION_KEEP_DAILY_KEY) == "2"
    assert setting_value(snapshots.RETENTION_MAX_AGE_DAYS_KEY) == "11"
    assert setting_value(snapshots.RETENTION_HARD_CAP_KEY) == "9"
    assert snapshots.retention_policy() == policy


def test_set_retention_policy_joins_the_callers_session() -> None:
    policy = snapshots.RetentionPolicy(keep_last_n=5, keep_daily=1, max_age_days=2, hard_cap=4)

    with Session(engine) as session:
        snapshots.set_retention_policy(policy, session=session)
        assert session.get(AppConfig, snapshots.RETENTION_KEEP_LAST_N_KEY).value == "5"
        assert session.get(AppConfig, snapshots.RETENTION_HARD_CAP_KEY).value == "4"
        session.commit()

    assert snapshots.retention_policy() == policy


def test_set_retention_policy_writes_nothing_when_validation_fails() -> None:
    bypassed = snapshots.RetentionPolicy()
    object.__setattr__(bypassed, "keep_last_n", 0)

    with pytest.raises(ValueError) as caught:
        snapshots.set_retention_policy(bypassed)

    assert "keep_last_n" in str(caught.value)
    for key in RETENTION_KEYS:
        assert setting_value(key) is None


def test_a_provider_reads_the_policy_once_at_construction(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    store_setting(snapshots.RETENTION_KEEP_LAST_N_KEY, "4")

    provider = snapshots.LocalCopyProvider(root)
    store_setting(snapshots.RETENTION_KEEP_LAST_N_KEY, "9")

    assert provider.policy.keep_last_n == 4
    assert snapshots.retention_policy().keep_last_n == 9
