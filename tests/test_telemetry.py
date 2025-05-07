import sqlite3
import importlib
import json
import pytest

from cli_telemetry import telemetry


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    # Redirect HOME to a temp directory for isolation
    # Redirect HOME and XDG_DATA_HOME to a temp directory for isolation
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Reload telemetry module to reset state
    importlib.reload(telemetry)
    yield
    monkeypatch.delenv("HOME", raising=False)


def test_service_files_created(tmp_path):
    service = "testsvc"
    telemetry.init_telemetry(service)
    # Files live under XDG_DATA_HOME/cli-telemetry/<service>
    base = tmp_path / "cli-telemetry" / service
    db_file = base / "telemetry.db"
    uid_file = base / "telemetry_user_id"
    assert db_file.exists()
    assert uid_file.exists()
    # DB table exists
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='otel_spans'")
    assert cur.fetchone() is not None
    conn.close()


def test_profile_decorator_writes_span(tmp_path):
    service = "testsvc2"
    teleport = telemetry
    teleport.init_telemetry(service)

    @teleport.profile
    def foo():
        return "bar"

    teleport.start_session("foo", service_name=service)
    result = foo()
    teleport.end_session()

    assert result == "bar"
    # DB file under XDG_DATA_HOME/cli-telemetry/<service>
    db_file = tmp_path / "cli-telemetry" / service / "telemetry.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT name FROM otel_spans WHERE name='foo'")
    rows = cur.fetchall()
    assert len(rows) >= 1
    conn.close()


def test_profile_block_and_add_tag(tmp_path):
    service = "testsvc3"
    telemetry.init_telemetry(service)
    telemetry.start_session("block_cmd", service_name=service)

    with telemetry.profile_block("my_block", tags={"foo": "bar"}):
        telemetry.add_tag("baz", 123)

    telemetry.end_session()

    # DB file under XDG_DATA_HOME/cli-telemetry/<service>
    db_file = tmp_path / "cli-telemetry" / service / "telemetry.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT attributes FROM otel_spans WHERE name='my_block'")
    row = cur.fetchone()
    assert row is not None
    attrs = json.loads(row[0])
    assert attrs["foo"] == "bar"
    assert attrs["baz"] == 123
    conn.close()
