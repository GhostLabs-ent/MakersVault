from pathlib import Path

import pytest

from content_store import (
    ContentAlreadyExists,
    ContentStore,
    InvalidStoreKey,
    LocalContentStore,
    normalize_store_key,
)


def write_staged(store: LocalContentStore, namespace: str, data: bytes) -> Path:
    path = store.staging_path(namespace)
    path.write_bytes(data)
    return path


def test_local_adapter_declares_and_satisfies_contract(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    assert isinstance(store, ContentStore)
    assert all(vars(store.capabilities).values())


@pytest.mark.parametrize("key", ["", "/absolute", "../escape", "a/../escape", "a\\b", "a//b", "."])
def test_store_keys_fail_closed(key):
    with pytest.raises(InvalidStoreKey):
        normalize_store_key(key)


def test_publish_stream_stat_and_materialize(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    staged = write_staged(store, "operation-1", b"model-bytes")

    result = store.publish(staged, "revisions/asset/revision/model.stl")

    assert result.size == 11
    assert not staged.exists()
    assert store.exists(result.key)
    with store.open_read(result.key) as source:
        assert source.read(5) == b"model"
        assert source.read() == b"-bytes"
    with store.materialize(result.key) as local:
        assert local.read_bytes() == b"model-bytes"


def test_create_if_absent_does_not_overwrite(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    first = write_staged(store, "first", b"first")
    store.publish(first, "objects/value")
    second = write_staged(store, "second", b"second")

    with pytest.raises(ContentAlreadyExists):
        store.publish(second, "objects/value")

    assert second.read_bytes() == b"second"
    assert store.local_path("objects/value").read_bytes() == b"first"


def test_overwrite_publish_is_atomic_and_local(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    store.publish(write_staged(store, "first", b"first"), "objects/value")
    store.publish(write_staged(store, "second", b"second"), "objects/value", overwrite=True)
    assert store.local_path("objects/value").read_bytes() == b"second"


def test_bounded_enumeration_and_capacity(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    for index in range(5):
        store.publish(write_staged(store, f"stage-{index}", str(index).encode()), f"objects/{index}")

    batches = list(store.iter_key_batches("objects", batch_size=2))

    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert sorted(key for batch in batches for key in batch) == [f"objects/{index}" for index in range(5)]
    capacity = store.capacity("future/item")
    assert capacity.total >= capacity.used
    assert capacity.free >= 0


def test_reversible_delete_rolls_back(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    store.publish(write_staged(store, "source", b"recoverable"), "objects/value")

    ticket = store.prepare_delete(["objects/value"], "delete-1")
    assert not store.exists("objects/value")
    assert len(ticket.moves) == 1

    store.rollback_delete(ticket)
    assert store.local_path("objects/value").read_bytes() == b"recoverable"


def test_reversible_delete_commits(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    store.publish(write_staged(store, "source", b"delete-me"), "objects/value")

    ticket = store.prepare_delete(["objects/value"], "delete-2")
    quarantine = store.local_path(ticket.moves[0].quarantine_key)
    assert quarantine.exists()

    store.commit_delete(ticket)
    assert not quarantine.exists()
    assert not store.exists("objects/value")


def test_read_rejects_managed_symlink(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    link = store.local_path("objects/link")
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    with pytest.raises(InvalidStoreKey):
        store.open_read("objects/link")


def test_path_rejects_intermediate_directory_symlink(tmp_path):
    store = LocalContentStore(tmp_path / "storage")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload").write_bytes(b"outside")
    store.local_path("links").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidStoreKey):
        store.open_read("links/payload")
