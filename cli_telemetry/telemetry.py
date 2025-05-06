"""
Simple telemetry implementation for CLIs.

Features:
- Session management (`start_session`, `end_session`)
- `@profile` decorator for function-level spans
- `profile_block` context manager for code block spans
- `add_tag` to annotate the current span
- SQLiteSpanExporter with configurable DB location following XDG_DATA_HOME
"""

import os
import uuid
import sqlite3
import threading
import json
import time
from contextlib import contextmanager
from functools import wraps

# globals
_LOCK = threading.Lock()
_initialized = False
_conn = None
_trace_id = None
_root_span = None
_tls = threading.local()


def _get_span_stack():
    if not hasattr(_tls, "span_stack"):
        _tls.span_stack = []
    return _tls.span_stack


def _init_db_file(db_file: str):
    """Initialize SQLite connection and table at given path."""
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    global _conn
    _conn = sqlite3.connect(db_file, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("""
CREATE TABLE IF NOT EXISTS otel_spans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id TEXT NOT NULL,
  span_id TEXT NOT NULL,
  parent_span_id TEXT,
  name TEXT NOT NULL,
  start_time INTEGER NOT NULL,
  end_time INTEGER NOT NULL,
  attributes TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  events TEXT NOT NULL
);
""")
    _conn.commit()


def init_telemetry(service_name: str, db_path: str = None, user_id_file: str = None) -> None:
    """
    Initialize trace ID, user ID file, and SQLite DB.
    If db_path or user_id_file are given, use those paths;
    otherwise default under XDG_DATA_HOME/<service_name>/...
    """
    global _initialized, _trace_id
    with _LOCK:
        if _initialized:
            return

        # determine XDG base
        xdg = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        base = os.path.join(xdg, service_name)

        # user‐ID file
        if user_id_file:
            uid_path = os.path.expanduser(user_id_file)
        else:
            os.makedirs(base, exist_ok=True)
            uid_path = os.path.join(base, "telemetry_user_id")
        try:
            if not os.path.exists(uid_path):
                uid = str(uuid.uuid4())
                os.makedirs(os.path.dirname(uid_path), exist_ok=True)
                with open(uid_path, "w") as f:
                    f.write(uid)
        except OSError:
            pass

        # new trace ID
        _trace_id = str(uuid.uuid4())

        # DB file
        if db_path:
            db_file = os.path.expanduser(db_path)
        else:
            os.makedirs(base, exist_ok=True)
            db_file = os.path.join(base, "telemetry.db")

        _init_db_file(db_file)
        _initialized = True


class Span:
    def __init__(self, name: str, attributes: dict = None):
        self.name = name
        self.attributes = dict(attributes) if attributes else {}
        self.parent = None
        self.span_id = uuid.uuid4().hex
        self.start_time = None
        self.end_time = None
        self.status_code = 0
        self.events = []

    def __enter__(self):
        stack = _get_span_stack()
        if stack:
            self.parent = stack[-1]
        self.start_time = time.time_ns()
        stack.append(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.end_time = time.time_ns()
        if exc is not None:
            self.attributes["exception"] = str(exc)
            self.status_code = 1
        stack = _get_span_stack()
        if stack and stack[-1] is self:
            stack.pop()
        _export_span(self)
        return False

    def set_attribute(self, key: str, value):
        self.attributes[key] = value


def _export_span(span: Span):
    """Write a completed span into the SQLite table."""
    global _conn, _trace_id
    if _conn is None:
        return
    trace_id = _trace_id
    span_id = span.span_id
    parent_id = span.parent.span_id if span.parent else None
    start_time = int(span.start_time / 1_000)  # μs
    end_time = int(span.end_time / 1_000)
    attr_json = json.dumps(span.attributes)
    events_json = json.dumps(span.events)
    cur = _conn.cursor()
    cur.execute(
        """
INSERT INTO otel_spans
  (trace_id, span_id, parent_span_id, name,
   start_time, end_time, attributes, status_code, events)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
        (
            trace_id,
            span_id,
            parent_id,
            span.name,
            start_time,
            end_time,
            attr_json,
            span.status_code,
            events_json,
        ),
    )
    _conn.commit()


def profile(func):
    """Decorator: wrap a function in a Span."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        span = Span(func.__name__)
        span.__enter__()
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            span.attributes["exception"] = str(exc)
            span.status_code = 1
            span.__exit__(None, None, None)
            raise
        finally:
            # exit span if not already done
            if span.end_time is None:
                span.__exit__(None, None, None)

    return wrapper


@contextmanager
def profile_block(name: str, tags: dict = None):
    """Context manager: wrap a code block in a Span."""
    span = Span(name)
    span.__enter__()
    if tags:
        for k, v in tags.items():
            span.set_attribute(k, v)
    try:
        yield
    except Exception as exc:
        span.attributes["exception"] = str(exc)
        span.status_code = 1
        span.__exit__(None, None, None)
        raise
    else:
        span.__exit__(None, None, None)


def add_tag(key: str, value):
    """Add a tag to the current span on the stack."""
    stack = _get_span_stack()
    if stack:
        stack[-1].set_attribute(key, value)


def start_session(command_name: str, service_name: str = "mycli", db_path: str = None, user_id_file: str = None):
    """
    Begin a root span for the CLI invocation.
    Must call end_session() when done.
    """
    init_telemetry(service_name, db_path=db_path, user_id_file=user_id_file)
    global _root_span
    _root_span = Span("cli_invocation", attributes={"cli.command": command_name})
    _root_span.__enter__()


def end_session():
    """End the root invocation span and close the DB."""
    global _root_span, _conn
    if _root_span:
        _root_span.__exit__(None, None, None)
        _root_span = None
    if _conn:
        try:
            _conn.commit()
            _conn.close()
        except Exception:
            pass
