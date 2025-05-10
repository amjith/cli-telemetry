# cli-telemetry
Telemetry agent for CLI tools. Backed by SQLite

# Getting Started

Install it using `pip` or `uv`

```bash
uv pip install cli-telemetry
```


# Usage

Use it with any python script. Here's an example to show how to use it with a Click based CLI.

```python

@click.group()
@click.pass_context
def cli(ctx):
    # Start the root span for this invocation
    cmd = ctx.invoked_subcommand or "cli"
    start_session(command_name=cmd, service_name="example-cli")
    # Ensure we end the span when the CLI exits
    ctx.call_on_close(end_session)

@cli.command()
@profile
def work():
    """Simulate some nested work using a profile_block."""
    add_tag("phase", "start_work")
    with profile_block("step_1", tags={"step": 1}):
        click.echo("step1")
        sleep(0.1)
        pass
    with profile_block("step_2", tags={"step": 2}):
        click.echo("step2")
        sleep(0.2)
        pass
    click.echo("Work done!")

if __name__ == "__main__":
    cli()
```

Running this CLI will automatically record performance stats in a SQLite database. The SQLite database is located under `$XDG_DATA_HOME` (`~/.local/share/cli-telemetry/`).

You can view the traces using the built in viewer:

```bash
cli-telemetry
```

This is a menu driven interface to visualize your traces.

```bash
Available databases:
  [1] example-cli (/Users/amjith/.local/share/cli-telemetry/example-cli/telemetry.db)
Select database [1] (1):

Available traces:
  [1] 6c35e820-951f-4544-94e0-42ddd03a15f4 (command: 'work' at 2025-05-06T17:46:50)
  [2] c748efc2-6f34-42b9-876c-333b9fb406d5 (command: 'shout' at 2025-05-06T17:46:30)
  [3] 3b9a0b4c-ee73-4aa9-988b-d67037c5836d (command: 'shout' at 2025-05-06T08:16:51)
Select trace [1/2/3] (1):
root • 936.83ms (100%)
└── cli_invocation • 936.83ms (100.0%)
    └── work • 622.85ms (66.5%)
        └── step_1 • 105.06ms (11.2%)            step_2 • 204.88ms (21.9%)

```

## Web-Based Viewer

The web-based telemetry viewer is provided as a plugin. To serve the web UI:

```bash
cli-telemetry webapp --db-file ~/.local/share/cli-telemetry/<service>/telemetry.db \
    --host 127.0.0.1 --port 5000
```

## Folded Stack Exporter

The folded stack exporter is provided as a plugin. It generates a flame-graph style folded stacks file.

```bash
cli-telemetry folded \
  --db-file ~/.local/share/cli-telemetry/<service>/telemetry.db \
  --trace-id YOUR_TRACE_ID \
  --output-file trace.folded
```

Omit `--output-file` to print the folded stacks to stdout.

## Plugin Architecture

cli-telemetry supports plugins to extend its CLI:

- Built-in plugins are discovered in the `cli_telemetry.plugins` namespace package.
- External plugins can be installed and registered via setuptools entry
  points under the group `cli_telemetry.plugins`.

Plugins must define a `register(cli_group)` function, which takes the main Click
group and registers commands or options. For example:

```python
import click

def register(cli):
    @cli.command()
    def hello():
        """A simple hello command."""
        click.echo("Hello from plugin!")
```

External plugins should declare their entry point in their packaging:

```toml
[project.entry-points."cli_telemetry.plugins"]
myplugin = "my_plugin.module:register"
```

