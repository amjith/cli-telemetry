# cli-telemetry
Requires Python 3.10 or higher.

## Overview
cli-telemetry is a Python library and command-line interface for collecting, storing, and visualizing performance telemetry of CLI applications. It provides simple APIs to instrument code, records execution spans in a local SQLite database, and offers an interactive TUI to explore recorded traces.

## Key Features
- Lightweight instrumentation via decorators, context managers, or manual API calls
- Automatic instrumentation modules for Click commands, HTTPX requests, and subprocess calls
- Per-service SQLite backend under `$XDG_DATA_HOME/cli-telemetry/<service>/telemetry.db`
- Interactive trace viewer (`cli-telemetry`) with menu-driven navigation
- Exporters to generate speedscope-compatible JSON and flame graph visualizations

## Architecture & Directory Structure
```text
cli_telemetry/           # Main package
├── cli.py               # Core CLI commands and plugin loader
├── telemetry.py         # Core API: session/span management
├── instrumentation/     # Auto-instrumentation modules
│   ├── instrument_click.py
│   ├── instrument_httpx.py
│   └── instrument_subprocess.py
├── exporters/           # Trace exporters (speedscope, flame)
│   ├── speedscope.py
│   └── view_flame.py
├── plugins/             # Plugin architecture and built-in plugins
│   ├── __init__.py      # Namespace package for plugins
│   ├── speedscope_plugin/  # Folded stack export plugin
│   │   └── plugin.py
│   └── webapp_plugin/   # Web UI viewer plugin based on Flask
│       ├── plugin.py
│       └── webapp_static/
└── __main__.py          # `python -m cli_telemetry` entrypoint

examples/                # Sample scripts demonstrating usage
tests/                   # Pytest suite for core functionality
AGENTS.md                # LLM context about architecture and usage
README.md                # Project overview and example
TODO.md                  # Planned enhancements
tox.ini                  # Testing and linting configuration
pyproject.toml           # Project metadata and dependencies
```

## Installation
```bash
pip install cli-telemetry
```

## Basic Usage
1. Instrument your CLI code:
   ```python
   import click
   from cli_telemetry import start_session, end_session, profile, profile_block, add_tag

   @click.group()
   @click.pass_context
   def cli(ctx):
       cmd = ctx.invoked_subcommand or "my-cli"
       start_session(command_name=cmd, service_name="my-cli")
       ctx.call_on_close(end_session)

   @cli.command()
   @profile
   def task():
       add_tag("phase", "start")
       with profile_block("step1", tags={"step": 1}):
           click.echo("Running step 1")
       click.echo("Done")
   ```
2. Run your CLI to record telemetry:
   ```bash
   python my_cli.py task
   ```
3. Launch the interactive viewer:
   ```bash
   cli-telemetry
   ```

## Plugin Architecture

cli-telemetry supports extensible plugins to extend its CLI:

- Built-in plugins are discovered in the `cli_telemetry.plugins` namespace package via Python’s `pkgutil`.
- External plugins can be installed via setuptools entry points in the `cli_telemetry.plugins` group.
- Plugins must define a `register(cli_group)` function that attaches commands or options to the main Click group.

Example plugin:

```python
import click

def register(cli):
    @cli.command()
    def hello():
        """Simple hello command from a plugin."""
        click.echo("Hello from plugin!")
```

To enable an external plugin, declare its entry point in your package:

```toml
[project.entry-points."cli_telemetry.plugins"]
myplugin = "my_plugin.module:register"
```

## Testing
Run the test suite with:
```bash
pytest
```

## Contributing
- Fork the repository and create a feature branch
- Ensure new code is covered by tests
- Run linters and formatters (`pre-commit run --all-files`)
- Submit a pull request for review
