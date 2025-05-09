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
import platform
import inspect
import sysconfig
import site
import os as _os
from contextlib import contextmanager
from functools import wraps
from typing import Optional

# Determine directories to skip when locating user code
#  - this agent's own package
#  - Python standard library dirs
#  - site-packages dirs
from importlib.metadata import version, PackageNotFoundError
# Path to this package
_AGENT_PATH = os.path.dirname(__file__)
# Standard library paths
_STDLIB_PATHS = set()
try:
    _STDLIB_PATHS.add(sysconfig.get_path('stdlib'))
    _STDLIB_PATHS.add(sysconfig.get_path('platstdlib'))
except Exception:
    pass
# Site-packages paths
_SITE_PACKAGES = set()
try:
    _SITE_PACKAGES.update(site.getsitepackages())
except Exception:
    pass
# Aggregate all skip paths
_SKIP_PATHS = {_AGENT_PATH}
_SKIP_PATHS |= {p for p in _STDLIB_PATHS if p}
_SKIP_PATHS |= {p for p in _SITE_PACKAGES if p}


def _find_user_caller() -> tuple[str, int]:
    """Walk the call stack to find the first frame outside agent, stdlib, and site-packages."""
    for frame_info in inspect.stack():
        filename = frame_info.filename
        # normalize path
        try:
            abspath = _os.path.abspath(filename)
        except Exception:
            abspath = filename
        # skip frames under any of the skip directories
        if any(abspath.startswith(p) for p in _SKIP_PATHS):
            continue
        # Found a user-level frame
        return abspath, frame_info.lineno
    # Fallback to immediate caller
    fr = inspect.currentframe().f_back
    return fr.f_code.co_filename, fr.f_lineno

# Globals
_LOCK = threading.Lock()
_initialized = False
_conn: Optional[sqlite3.Connection] = None
_trace_id: Optional[str] = None
_root_span = None
_tls = threading.local()

# Common tags applied to every span
COMMON_TAGS: dict[str, object] = {}


def add_common_tag(key: str, value: object) -> None:
    """Register a common tag that will be merged into every new Span."""
    COMMON_TAGS[key] = value


def _get_span_stack() -> list["Span"]:
    if not hasattr(_tls, "span_stack"):
        _tls.span_stack = []
    return _tls.span_stack


def _init_db_file(db_file: str) -> None:
    """Initialize SQLite connection and table at the given path."""
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


def init_telemetry(service_name: str, db_path: Optional[str] = None, user_id_file: Optional[str] = None) -> None:
    from .instrumentation import init_auto_instrumentation

    """
    Initialize trace ID, user‐ID file, and SQLite DB.
    If db_path/user_id_file are provided, uses those; otherwise defaults to:
      XDG_DATA_HOME/cli-telemetry/<service_name>/telemetry.db
      XDG_DATA_HOME/cli-telemetry/<service_name>/telemetry_user_id
    Also seeds COMMON_TAGS with user-ID, trace-ID, OS, Python, and CLI version.
    """
    global _initialized, _trace_id
    with _LOCK:
        if _initialized:
            return

        init_auto_instrumentation()

        # determine base path under XDG_DATA_HOME
        xdg = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        base = os.path.join(xdg, "cli-telemetry", service_name)
        os.makedirs(base, exist_ok=True)

        # user‐ID file
        if user_id_file:
            uid_path = os.path.expanduser(user_id_file)
        else:
            uid_path = os.path.join(base, "telemetry_user_id")
        try:
            if not os.path.exists(uid_path):
                os.makedirs(os.path.dirname(uid_path), exist_ok=True)
                with open(uid_path, "w") as f:
                    f.write(str(uuid.uuid4()))
            with open(uid_path) as f:
                COMMON_TAGS["telemetry.user_id"] = f.read().strip()
        except Exception:
            COMMON_TAGS["telemetry.user_id"] = str(uuid.uuid4())

        # trace-ID
        _trace_id = str(uuid.uuid4())
        COMMON_TAGS["telemetry.trace_id"] = _trace_id

        # platform info
        COMMON_TAGS["os.system"] = platform.system()
        COMMON_TAGS["os.release"] = platform.release()
        COMMON_TAGS["python.version"] = platform.python_version()

        # CLI version (if package installed)
        try:
            COMMON_TAGS["cli.version"] = version(service_name)
        except PackageNotFoundError:
            COMMON_TAGS["cli.version"] = "unknown"

        # DB path
        if db_path:
            db_file = os.path.expanduser(db_path)
        else:
            db_file = os.path.join(base, "telemetry.db")

        _init_db_file(db_file)
        _initialized = True


class Span:
    """Context‐manager span for timing and attribute collection."""

    def __init__(self, name: str, attributes: dict[str, object] = None):
        self.name = name
        # Initialize attributes and capture source location if not provided
        self.attributes = dict(attributes) if attributes else {}
        # Auto-capture user code location if not provided
        if self.attributes.get("source.file") is None or self.attributes.get("source.line") is None:
            src_file, src_line = _find_user_caller()
            self.attributes["source.file"] = src_file
            self.attributes["source.line"] = src_line
        self.parent: Optional[Span] = None
        self.span_id = uuid.uuid4().hex
        self.start_time: Optional[int] = None
        self.end_time: Optional[int] = None
        self.status_code = 0
        self.events: list[dict] = []

    def __enter__(self) -> "Span":
        stack = _get_span_stack()
        if stack:
            self.parent = stack[-1]
        # merge common tags
        for k, v in COMMON_TAGS.items():
            self.attributes.setdefault(k, v)
        self.start_time = time.time_ns()
        stack.append(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.end_time = time.time_ns()
        if exc is not None:
            self.attributes["exception"] = str(exc)
            self.status_code = 1
        stack = _get_span_stack()
        if stack and stack[-1] is self:
            stack.pop()
        _export_span(self)
        return False

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


def _export_span(span: Span) -> None:
    """Persist a finished Span into SQLite."""
    global _conn, _trace_id
    if _conn is None or span.start_time is None or span.end_time is None:
        return
    parent_id = span.parent.span_id if span.parent else None
    start_us = span.start_time // 1_000
    end_us = span.end_time // 1_000
    cur = _conn.cursor()
    cur.execute(
        """
INSERT INTO otel_spans
  (trace_id, span_id, parent_span_id, name,
   start_time, end_time, attributes, status_code, events)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
        (
            _trace_id,
            span.span_id,
            parent_id,
            span.name,
            start_us,
            end_us,
            json.dumps(span.attributes),
            span.status_code,
            json.dumps(span.events),
        ),
    )
    _conn.commit()


def profile(func):
    """Decorator: wrap function execution in a Span."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Capture function definition location
        src_file = func.__code__.co_filename
        src_line = func.__code__.co_firstlineno
        span = Span(func.__name__, attributes={
            "source.file": src_file,
            "source.line": src_line,
        })
        span.__enter__()
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            span.attributes["exception"] = str(exc)
            span.status_code = 1
            span.__exit__(None, None, None)
            raise
        finally:
            if span.end_time is None:
                span.__exit__(None, None, None)

    return wrapper


@contextmanager
def profile_block(name: str, tags: dict[str, object] = None):
    """Context manager: wrap a block of code in a Span."""
    # Determine user invocation location
    src_file, src_line = _find_user_caller()
    span = Span(name, attributes={
        "source.file": src_file,
        "source.line": src_line,
    })
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


def add_tag(key: str, value: object) -> None:
    """Add or override a tag on the current span."""
    stack = _get_span_stack()
    if stack:
        stack[-1].set_attribute(key, value)

def add_tags(tags: dict[str, object]) -> None:
    """Add or override multiple tags on the current span."""
    for key, value in tags.items():
        add_tag(key, value)


def start_session(command_name: str, service_name: str = "mycli", db_path: str = None, user_id_file: str = None) -> None:
    """
    Start a root CLI invocation Span.
    Must call end_session() when done.
    """
    init_telemetry(service_name, db_path=db_path, user_id_file=user_id_file)
    global _root_span
    _root_span = Span("cli_invocation", attributes={"cli.command": command_name})
    _root_span.__enter__()


def end_session() -> None:
    """End the root invocation Span and close the database."""
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
