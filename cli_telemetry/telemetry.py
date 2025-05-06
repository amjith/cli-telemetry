"""
Telemetry library using OpenTelemetry and SQLite.

Features:
- Session management (`start_session`, `end_session`)
- `@profile` decorator for function-level spans
- `profile_block` context manager for code block spans
- `add_tag` to annotate the current span
- SQLiteSpanExporter for per-service persistent storage
"""

import os
import uuid
import sqlite3
import threading
import json
from contextlib import contextmanager
from functools import wraps
from typing import Sequence

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import (
    SpanExporter,
    SpanExportResult,
    BatchSpanProcessor,
)

# Thread-safety lock
_LOCK = threading.Lock()
_initialized = False
_root_ctx = None
_tracer = None


def _get_user_id(path: str) -> str:
    """Get or create an anonymized user ID stored at the given path."""
    try:
        if os.path.exists(path):
            return open(path).read().strip()
        uid = str(uuid.uuid4())
        with open(path, "w") as f:
            f.write(uid)
        return uid
    except OSError:
        return str(uuid.uuid4())


class SQLiteSpanExporter(SpanExporter):
    """Exports finished spans into a local SQLite database."""

    def __init__(self, db_path: str):
        db_path = os.path.expanduser(db_path)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
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
        self._conn.commit()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        cur = self._conn.cursor()
        for span in spans:
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, "032x")
            span_id = format(ctx.span_id, "016x")
            parent_id = format(span.parent.span_id, "016x") if span.parent else None
            attr_json = json.dumps(span.attributes)
            events_json = json.dumps(
                [
                    {
                        "name": evt.name,
                        "attributes": evt.attributes,
                        "timestamp": evt.timestamp,
                    }
                    for evt in span.events
                ]
            )
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
                    int(span.start_time / 1_000),  # ns -> μs
                    int(span.end_time / 1_000),
                    attr_json,
                    span.status.status_code.value,
                    events_json,
                ),
            )
        self._conn.commit()
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self._conn.commit()
        self._conn.close()


def init_telemetry(service_name: str) -> None:
    """Initialize OpenTelemetry tracer and SQLite exporter for the given service."""
    global _initialized, _tracer
    with _LOCK:
        if _initialized:
            return
        home = os.path.expanduser("~")
        db_path = f"{home}/.{service_name}_telemetry.db"
        user_id_file = f"{home}/.{service_name}_telemetry_user_id"
        session_id = str(uuid.uuid4())
        user_id = _get_user_id(user_id_file)
        resource = Resource(
            {
                "service.name": service_name,
                "telemetry.user_id": user_id,
                "telemetry.session_id": session_id,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = SQLiteSpanExporter(db_path)
        processor = BatchSpanProcessor(exporter, max_export_batch_size=50)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        _initialized = True


def profile(func):
    """Decorator that creates an OpenTelemetry span for the duration of the function."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if _tracer is None:
            init_telemetry()
        with _tracer.start_as_current_span(
            func.__name__, kind=SpanKind.INTERNAL
        ) as span:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise

    return wrapper


@contextmanager
def profile_block(name: str, tags: dict = None):
    """Context manager to create a span around a block of code."""
    if _tracer is None:
        init_telemetry()
    with _tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as span:
        if tags:
            for k, v in tags.items():
                span.set_attribute(k, v)
        yield


def add_tag(key: str, value):
    """Add an attribute to the current span."""
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute(key, value)


def start_session(command_name: str, service_name: str = "mycli"):
    """Start a root span for the CLI invocation."""
    init_telemetry(service_name)
    global _root_ctx
    _root_ctx = _tracer.start_as_current_span(
        "cli_invocation",
        kind=SpanKind.INTERNAL,
        attributes={"cli.command": command_name},
    )
    _root_ctx.__enter__()


def end_session():
    """End the root invocation span and shutdown the tracer provider."""
    global _root_ctx
    if _root_ctx:
        _root_ctx.__exit__(None, None, None)
        _root_ctx = None
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()
