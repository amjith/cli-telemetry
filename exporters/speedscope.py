#!/usr/bin/env python3
"""
speedscope.py

Reads spans from your SQLite telemetry DB and emits
FlameGraph-style folded stacks:

    root;child;subchild <duration_us>

You can then load the resulting file into Speedscope
(via “Import” → “Text (FlameGraph)”).
"""

import sqlite3
import argparse
import sys


def load_spans(db_path: str, trace_id: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT span_id, parent_span_id, name, start_time, end_time
          FROM otel_spans
         WHERE trace_id = ?
      ORDER BY start_time
    """,
        (trace_id,),
    )
    rows = cur.fetchall()
    conn.close()

    spans = {}
    for span_id, parent_id, name, start_us, end_us in rows:
        spans[span_id] = {
            "parent": parent_id,
            "name": name,
            "start": start_us,
            "end": end_us,
        }
    return spans


def build_path(span_id: str, spans: dict):
    path = []
    current = spans.get(span_id)
    while current:
        path.append(current["name"])
        parent = current["parent"]
        current = spans.get(parent)
    return list(reversed(path))


def export_folded(spans: dict, min_us: int = 1):
    """
    For each span, prints:
      root;child;...;thisspan <duration_us>
    """
    for sid, info in spans.items():
        dur = info["end"] - info["start"]
        if dur < min_us:
            continue
        stack = build_path(sid, spans)
        # join with semicolon, then a space, then the count (microseconds)
        print(f"{';'.join(stack)} {dur}")


def main():
    p = argparse.ArgumentParser(description="Export SQLite spans to folded-stack for Speedscope")
    p.add_argument("--db", "-d", required=True, help="Path to telemetry.db")
    p.add_argument("--trace", "-t", required=True, help="Trace ID to export")
    p.add_argument("--min-us", type=int, default=1, help="Omit spans shorter than this (μs)")
    args = p.parse_args()

    spans = load_spans(args.db, args.trace)
    if not spans:
        sys.exit(f"No spans found for trace {args.trace}")
    export_folded(spans, min_us=args.min_us)


if __name__ == "__main__":
    main()
