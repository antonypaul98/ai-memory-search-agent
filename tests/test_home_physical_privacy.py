from __future__ import annotations

import pytest

from app.db.home_physical_privacy import (
    delete_user_home_physical_data,
    export_user_home_physical_data,
)


class FakeResult:
    def __init__(self, *, rows=None, rowcount=0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, statements, results):
        self.statements = statements
        self.results = iter(results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((" ".join(str(statement).split()), params))
        return next(self.results)


def test_export_is_exact_tenant_and_excludes_raw_image_bytes():
    statements = []
    results = [
        FakeResult(rows=[{"evidence_id": "obs-a", "object_name": "keys"}]),
        FakeResult(rows=[{"frame_id": "frame-a", "image_sha256": "abc"}]),
        FakeResult(rows=[{"object_id": "obj-a", "object_class": "keys", "identity_kind": "class"}]),
        FakeResult(rows=[{"observation_id": "obs-a", "object_id": "obj-a", "frame_id": "frame-a", "box_json": "[]"}]),
    ]
    exported = export_user_home_physical_data(
        lambda: FakeConnection(statements, results), user_id="tenant-a"
    )

    assert exported["sightings"][0]["object_name"] == "keys"
    assert exported["image_evidence"] == [{"frame_id": "frame-a", "image_sha256": "abc"}]
    assert all(params == ("tenant-a",) for _, params in statements)
    evidence_sql = statements[1][0]
    assert "image_sha256" in evidence_sql
    assert "image_bytes" not in evidence_sql


def test_delete_is_exact_tenant_and_orders_fk_dependents_first():
    statements = []
    results = [FakeResult(rowcount=n) for n in (2, 1, 1, 3)]
    deleted = delete_user_home_physical_data(
        lambda: FakeConnection(statements, results), user_id="tenant-a"
    )

    assert deleted == {
        "image_observations": 2,
        "image_evidence": 1,
        "physical_objects": 1,
        "sightings": 3,
    }
    assert all(params == ("tenant-a",) for _, params in statements)
    assert [sql.split()[2] for sql, _ in statements] == [
        "home_image_observations",
        "home_image_evidence",
        "home_physical_objects",
        "home_object_sightings",
    ]


def test_failure_escapes_connection_context_for_transaction_rollback():
    statements = []

    class FailingConnection(FakeConnection):
        def execute(self, statement, params=None):
            normalized = " ".join(str(statement).split())
            self.statements.append((normalized, params))
            if "home_image_evidence" in normalized:
                raise RuntimeError("injected failure")
            return FakeResult(rowcount=1)

    with pytest.raises(RuntimeError, match="injected failure"):
        delete_user_home_physical_data(
            lambda: FailingConnection(statements, []), user_id="tenant-a"
        )
    assert len(statements) == 2


@pytest.mark.parametrize("operation", [export_user_home_physical_data, delete_user_home_physical_data])
def test_blank_tenant_fails_before_query(operation):
    called = False

    def connect():
        nonlocal called
        called = True
        raise AssertionError("connection should not be opened")

    with pytest.raises(ValueError, match="user_id is required"):
        operation(connect, user_id="   ")
    assert called is False
