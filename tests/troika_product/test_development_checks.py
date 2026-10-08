import pytest

from troika_product.development_checks import DevelopmentCheckStore


@pytest.fixture
def store():
    value = DevelopmentCheckStore()
    value.heartbeat("owner", "pc", True)
    yield value
    value.purge("owner")


def job(store, **kwargs):
    return store.create("owner", "phone", "pc", "python_tests", {"main.py": "print(1)"}, "flow", **kwargs)


def test_owner_device_scope_claim_and_replay(store):
    queued = job(store)
    assert store.get("other", "phone", queued["id"]) is None
    assert store.get("owner", "another", queued["id"]) is None
    assert store.claim("other", "pc") is None
    claimed = store.claim("owner", "pc")
    assert claimed["files"] == {"main.py": "print(1)"}
    assert store.claim("owner", "pc") is None
    report = {"exit_code": 1, "output": "FAILED"}
    assert not store.finish("owner", "phone", queued["id"], claimed["lease"], report)
    assert not store.finish("owner", "pc", queued["id"], "wrong", report)
    assert store.finish("owner", "pc", queued["id"], claimed["lease"], report)
    assert not store.finish("owner", "pc", queued["id"], claimed["lease"], report)
    assert not store.jobs[queued["id"]].files
    assert store.get("owner", "phone", queued["id"])["report"]["exit_code"] == 1


def test_cancel_invalidates_lease_and_releases_source(store):
    queued = job(store)
    claimed = store.claim("owner", "pc")
    assert not store.cancel("other", "phone", queued["id"])
    assert store.cancel("owner", "phone", queued["id"])
    assert not store.jobs[queued["id"]].files
    assert not store.finish("owner", "pc", queued["id"], claimed["lease"], {"exit_code": 0})


def test_enrollment_expiry_and_revoke(store):
    clock = [100]
    store.clock = lambda: clock[0]
    store.heartbeat("owner", "pc", True)
    queued = job(store)
    clock[0] += 31
    with pytest.raises(ValueError, match="unavailable"):
        job(store)
    store.purge("owner", "phone")
    assert store.get("owner", "pc", queued["id"]) is None


@pytest.mark.parametrize("files", [{"../x": "bad"}, {".env": "secret"}, {"main.py": "x" * 120001}])
def test_malformed_or_oversized_source_never_reaches_worker(store, files):
    with pytest.raises(ValueError):
        store.create("owner", "phone", "pc", "python_tests", files, "flow")
    assert store.claim("owner", "pc") is None


def test_capacity_and_report_limits(store):
    job(store)
    job(store)
    with pytest.raises(ValueError, match="limit"):
        job(store)
    claimed = store.claim("owner", "pc")
    for report in [{"exit_code": True}, {"exit_code": 0, "output": "x" * 64001}, {"exit_code": 0, "no_tests": "false"}]:
        with pytest.raises(ValueError):
            store.finish("owner", "pc", claimed["id"], claimed["lease"], report)


def test_ttl_frees_source_and_report_without_another_request():
    import time
    value = DevelopmentCheckStore(ttl=0.03)
    value.heartbeat("owner", "pc", True)
    queued = job(value)
    deadline = time.monotonic() + 2
    while value.jobs and time.monotonic() < deadline:
        time.sleep(0.01)
    assert queued["id"] not in value.jobs
