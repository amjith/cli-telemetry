"""
Folded stack generator plugin for cli-telemetry.
Provides functions to load spans and export folded stacks, and
a CLI command to generate folded stack files.
"""
import os
import sqlite3
import json
import sys
import click

def load_spans(db_path: str, trace_id: str):
    """
    Load spans for a given trace_id, annotating display names to dedupe and
    append a key attribute value for context.
    Returns a dict of span_id -> {parent, name, start, end}.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT span_id, parent_span_id, name, start_time, end_time, attributes
          FROM otel_spans
         WHERE trace_id = ?
      ORDER BY start_time
        """,
        (trace_id,),
    )
    rows = cur.fetchall()
    conn.close()

    ATTRIBUTE_KEY_MAP = {
        "subprocess.run": "subprocess.command",
        "httpx.request": "http.url",
    }

    # Count raw name occurrences
    raw_counts: dict[str, int] = {}
    for _sid, _pid, raw_name, _s, _e, _attrs in rows:
        raw_counts[raw_name] = raw_counts.get(raw_name, 0) + 1
    # Track seen count per raw name
    seen_counts: dict[str, int] = {}
    spans: dict[str, dict] = {}
    for span_id, parent_id, raw_name, start_us, end_us, attrs_json in rows:
        try:
            attrs = json.loads(attrs_json)
        except Exception:
            attrs = {}
        # Source file and line for context
        src_file = attrs.get("source.file")
        src_line = attrs.get("source.line")
        if src_file and src_line is not None:
            try:
                abs_file = os.path.abspath(src_file)
            except Exception:
                abs_file = src_file
            file_line = f"{abs_file}:{src_line}"
        else:
            file_line = None
        # Context suffix from attribute, if any
        attr_key = ATTRIBUTE_KEY_MAP.get(raw_name)
        suffix = None
        val = attrs.get(attr_key)
        if val:
            if isinstance(val, (list, tuple)):
                suffix = " ".join(str(x) for x in val)
            else:
                suffix = str(val)
        # Compute display name with deduplication
        count = raw_counts.get(raw_name, 0)
        idx = seen_counts.get(raw_name, 0) + 1
        seen_counts[raw_name] = idx
        if count > 1:
            display_name = f"{raw_name} {suffix}" if suffix else f"{raw_name} [{idx}]"
        else:
            display_name = raw_name + (f" {suffix}" if suffix else "")
        if file_line:
            display_name = f"{display_name} ({file_line})"
        spans[span_id] = {
            "parent": parent_id,
            "name": display_name,
            "start": start_us,
            "end": end_us,
        }
    return spans

def build_path(span_id: str, spans: dict):
    """Construct the full stack path of names for the given span."""
    path = []
    current = spans.get(span_id)
    while current:
        path.append(current["name"])
        current = spans.get(current["parent"])
    return list(reversed(path))

def export_folded(spans: dict, out, min_us: int = 1):
    """
    Write folded stack entries (Speedscope format) to a file-like object:
      parent;child;...;span duration_us
    """
    for sid, info in spans.items():
        dur = info["end"] - info["start"]
        if dur < min_us:
            continue
        stack = build_path(sid, spans)
        print(f"{';'.join(stack)} {dur}", file=out)

def register(cli):
    """Register the 'folded' command to generate folded stack files."""
    @cli.command(name='folded')
    @click.option('--db-file', required=True, help='Path to telemetry.db file')
    @click.option('--trace-id', 'trace_id', required=True, help='Trace ID to export')
    @click.option('--output-file', default=None, help='File to write folded stacks (stdout otherwise)')
    @click.option('--min-us', default=1, type=int, help='Minimum span duration to include (µs)')
    def folded(db_file, trace_id, output_file, min_us):
        """Generate a folded stack file for a given trace."""
        spans = load_spans(db_file, trace_id)
        if output_file:
            with open(output_file, 'w') as out:
                export_folded(spans, out, min_us)
        else:
            export_folded(spans, sys.stdout, min_us)