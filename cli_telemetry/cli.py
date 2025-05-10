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
from contextlib import redirect_stdout
from cli_telemetry.exporters import view_flame
from rich.prompt import Prompt
import json
# Web interface functionality moved to plugin architecture; see plugins in cli_telemetry.plugins
@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """
    Browse available telemetry databases, visualize traces as flame graphs,
    or serve a web-based viewer.
    """
    if ctx.invoked_subcommand is None:
        _browse()



def _browse():
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

    # Load spans and export folded stacks to a central XDG_DATA_HOME directory
    spans = speedscope.load_spans(selected_db, trace_id)
    # Determine export directory and ensure it exists
    export_dir = os.path.join(xdg_data_home, "cli-telemetry", "folded-stacks")
    os.makedirs(export_dir, exist_ok=True)
    # Include timestamp in filename
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    filename = os.path.join(export_dir, f"trace_{trace_id}_{timestamp}.folded")
    # Write folded stacks to file
    with open(filename, "w") as f:
        with redirect_stdout(f):
            speedscope.export_folded(spans)
    # Print absolute path of the generated file
    abs_path = os.path.abspath(filename)
    click.echo(f"\nFolded stack file written to {abs_path}")
    # Prompt user to view the flame graph in the terminal now
    if click.confirm("Do you want to view the flame graph in the terminal now?", default=True):
        try:
            # Build and render a time-ordered tree view
            root = view_flame.build_tree_from_spans(spans, speedscope.build_path)
            total = root.get("_time", 0)
            human_total = view_flame.format_time(total)
            console_tree = view_flame.Tree(f"[b]root[/] • {human_total} (100%)")
            view_flame.render(root, console_tree, total)
            view_flame.print(console_tree)
        except Exception as e:
            click.echo(f"Error rendering flame graph: {e}", err=True)


"""
See `cli_telemetry.plugins` for available plugins.
"""
def _load_plugins(cli_group):
    """Load built-in and external plugins for cli-telemetry."""
    # Built-in plugins in cli_telemetry.plugins namespace
    try:
        import pkgutil
        import importlib
        from cli_telemetry import plugins
    except ImportError:
        # plugins namespace not available
        pass
    else:
        for _, name, _ in pkgutil.iter_modules(plugins.__path__):
            try:
                module = importlib.import_module(f"cli_telemetry.plugins.{name}")
                if hasattr(module, "register"):
                    module.register(cli_group)
            except Exception as e:
                click.echo(f"Error loading built-in plugin {name}: {e}", err=True)
                continue

    # External plugins via setuptools entry points
    import importlib.metadata as _meta
    # Retrieve entry points for group 'cli_telemetry.plugins'
    try:
        eps = _meta.entry_points(group="cli_telemetry.plugins")
    except TypeError:
        # Fallback for older metadata API
        try:
            eps = _meta.entry_points().get("cli_telemetry.plugins", [])
        except Exception:
            eps = []
    # Load each external plugin
    for ep in eps or []:
        try:
            plugin = ep.load()
            plugin(cli_group)
        except Exception as e:
            click.echo(f"Error loading plugin {ep.name}: {e}", err=True)
            continue

# Register plugins to extend CLI
_load_plugins(main)

if __name__ == "__main__":
    main()
