#!/usr/bin/env python3
"""
speedscope.py

Reads spans from your SQLite telemetry DB and either:

1) Lists all available traces with span count and first-captured timestamp.
2) Exports a single trace to FlameGraph-style folded stacks for Speedscope.

Usage:
  # List available traces:
  python export_to_speedscope.py --db telemetry.db --list

  # Export a specific trace:
  python export_to_speedscope.py --db telemetry.db --trace YOUR_TRACE_ID > trace.folded
"""

import sqlite3
import argparse
import sys
from datetime import datetime


def list_traces(db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT
          trace_id,
          COUNT(*)           AS span_count,
          MIN(start_time)    AS first_start_us
        FROM otel_spans
        GROUP BY trace_id
        ORDER BY first_start_us
    """)
    rows = cur.fetchall()
    conn.close()

    print("TRACE_ID\tSPANS\tFIRST_TIMESTAMP")
    for trace_id, count, first_us in rows:
        # convert microseconds since epoch to ISO timestamp
        ts = datetime.fromtimestamp(first_us / 1_000_000).isoformat()
        print(f"{trace_id}\t{count}\t{ts}")


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
        current = spans.get(current["parent"])
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
        print(f"{';'.join(stack)} {dur}")


def main():
    p = argparse.ArgumentParser(description="Export or list traces from SQLite spans DB for Speedscope")
    p.add_argument("--db", "-d", required=True, help="Path to telemetry.db")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--trace", "-t", help="Trace ID to export")
    group.add_argument("--list", action="store_true", help="List all trace IDs, span counts, and first-captured timestamps")
    p.add_argument("--min-us", type=int, default=1, help="Omit spans shorter than this (in μs)")
    args = p.parse_args()

    if args.list:
        list_traces(args.db)
        sys.exit(0)

    spans = load_spans(args.db, args.trace)
    if not spans:
        sys.exit(f"No spans found for trace {args.trace!r}")
    export_folded(spans, min_us=args.min_us)


if __name__ == "__main__":
    main()
