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
from rich.tree import Tree


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
    services = sorted(
        d for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d))
    )
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
    db_choice = click.prompt(
        "Select database", type=click.IntRange(1, len(dbs))
    )
    _, selected_db = dbs[db_choice - 1]

    # List latest 10 traces in the selected database
    conn = sqlite3.connect(selected_db)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT trace_id, MIN(start_time) AS ts
        FROM otel_spans
        GROUP BY trace_id
        ORDER BY ts DESC
        LIMIT 10
        """
    )
    traces = cur.fetchall()
    conn.close()
    if not traces:
        click.echo("No traces found in the selected database.", err=True)
        raise SystemExit(1)
    click.echo("\nAvailable traces:")
    for idx, (trace_id, ts) in enumerate(traces, start=1):
        dt = datetime.fromtimestamp(ts / 1_000_000).isoformat()
        click.echo(f"  [{idx}] {trace_id} (started at {dt})")
    trace_choice = click.prompt(
        "Select trace", type=click.IntRange(1, len(traces))
    )
    trace_id = traces[trace_choice - 1][0]

    # Load spans and build folded stacks
    spans = speedscope.load_spans(selected_db, trace_id)
    folded_lines = []
    for span_id, info in spans.items():
        duration = info["end"] - info["start"]
        if duration <= 0:
            continue
        path = speedscope.build_path(span_id, spans)
        folded_lines.append(f"{';'.join(path)} {duration}")

    # Render as a flame graph in the terminal
    root = view_flame.build_tree(folded_lines)
    total = root.get("_time", 0)
    human_total = view_flame.format_time(total)
    tree = Tree(f"[b]root[/] • {human_total} (100%)")
    view_flame.render(root, tree, total)
    print(tree)

if __name__ == "__main__":
    main()