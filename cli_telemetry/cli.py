#!/usr/bin/env python3
"""
cli.py

Command-line interface for browsing and visualizing telemetry traces as flame graphs.
"""

import os
import sqlite3
import click
from datetime import datetime
from cli_telemetry.exporters import speedscope
from cli_telemetry.exporters import view_flame
from rich import print
from rich.prompt import Prompt
from rich.tree import Tree
import json


@click.command()
def main():
    """
    Browse available telemetry databases and visualize selected traces.
    """
    # Locate telemetry databases under XDG_DATA_HOME or default
    xdg_data_home = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    base_dir = os.path.join(xdg_data_home, "cli-telemetry")
    if not os.path.isdir(base_dir):
        click.echo("No telemetry databases found.", err=True)
        raise SystemExit(1)
    # Find available service databases
    services = sorted(d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d)))
    dbs = []  # list of (service, path)
    for service in services:
        db_path = os.path.join(base_dir, service, "telemetry.db")
        if os.path.isfile(db_path):
            dbs.append((service, db_path))
    if not dbs:
        click.echo("No telemetry databases found.", err=True)
        raise SystemExit(1)
    click.echo("Available databases:")
    for idx, (service, path) in enumerate(dbs, start=1):
        click.echo(f"  [{idx}] {service} ({path})")
    db_indices = [str(i) for i in range(1, len(dbs) + 1)]
    # Default to the first database if none is entered
    db_choice = int(
        Prompt.ask(
            "Select database",
            choices=db_indices,
            default=db_indices[0],
        )
    )
    _, selected_db = dbs[db_choice - 1]

    # List latest 10 traces in the selected database, including root command tag if present
    conn = sqlite3.connect(selected_db)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.trace_id, t.ts, s.attributes
        FROM (
            SELECT trace_id, MIN(start_time) AS ts
            FROM otel_spans
            GROUP BY trace_id
            ORDER BY ts DESC
            LIMIT 10
        ) AS t
        LEFT JOIN otel_spans AS s
          ON s.trace_id = t.trace_id
         AND s.name = 'cli_invocation'
         AND s.start_time = t.ts
        """
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        click.echo("No traces found in the selected database.", err=True)
        raise SystemExit(1)
    # Parse trace list, extracting command from root span attributes
    traces = []  # list of (trace_id, ts, command)
    for trace_id, ts, attr_json in rows:
        command = None
        if attr_json:
            try:
                attrs = json.loads(attr_json)
                command = attrs.get("cli.command")
            except Exception:
                command = None
        traces.append((trace_id, ts, command))
    click.echo("\nAvailable traces:")
    for idx, (trace_id, ts, command) in enumerate(traces, start=1):
        # Format timestamp to seconds precision (no fractional part)
        dt = datetime.fromtimestamp(ts / 1_000_000).isoformat(timespec="seconds")
        if command:
            click.echo(f"  [{idx}] {trace_id} (command: {command!r} at {dt})")
        else:
            click.echo(f"  [{idx}] {trace_id} (started at {dt})")
    trace_indices = [str(i) for i in range(1, len(traces) + 1)]
    # Default to the first trace if none is entered
    trace_choice = int(
        Prompt.ask(
            "Select trace",
            choices=trace_indices,
            default=trace_indices[0],
        )
    )
    trace_id = traces[trace_choice - 1][0]

    # Load spans and build a tree preserving start-time ordering
    spans = speedscope.load_spans(selected_db, trace_id)
    # Build tree with aggregated durations and earliest start timestamp
    root = view_flame.build_tree_from_spans(spans, speedscope.build_path)
    total = root.get("_time", 0)
    human_total = view_flame.format_time(total)
    tree = Tree(f"[b]root[/] • {human_total} (100%)")
    view_flame.render(root, tree, total)
    print(tree)


if __name__ == "__main__":
    main()
