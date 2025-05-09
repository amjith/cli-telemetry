from time import sleep
import click
import httpx

# import this first so it can patch click before any commands are defined
import cli_telemetry.telemetry as telemetry
from cli_telemetry.telemetry import add_tag, profile_block

telemetry.init_telemetry("example-cli")


@click.group()
def cli():
    """Example CLI with telemetry instrumentation."""
    # no manual start_session() or call_on_close() needed any more
    pass


@cli.command()
@click.argument("message")
def echo(message):
    """Prints the message as-is."""
    # Tag the argument so it shows up on this span
    add_tag("args.message", message)
    click.echo(message)


@cli.command()
@click.argument("message")
@click.option("--times", "-n", default=1, show_default=True, help="How many times to shout")
def shout(message, times):
    """Prints the message uppercased with exclamation."""
    add_tag("args.message", message)
    add_tag("args.times", times)
    for _ in range(times):
        click.echo(f"{message.upper()}!")


@cli.command()
def fetch():
    """Fetch https://example.com to demonstrate HTTPX telemetry."""
    resp = httpx.get("https://example.com")
    click.echo(f"Fetched https://example.com [{resp.status_code}]")


@cli.command()
def work():
    """Simulate some nested work using a profile_block."""
    add_tag("phase", "start_work")
    with profile_block("step_1", tags={"step": 1}):
        click.echo("step1")
        sleep(0.1)
    with profile_block("step_2", tags={"step": 2}):
        click.echo("step2")
        sleep(0.2)
    click.echo("Work done!")
    # Example HTTPX call; instrumentation will record this as its own span
    try:
        resp = httpx.get("https://example.com")
        click.echo(f"Fetched https://example.com [{resp.status_code}]")
    except Exception as e:
        click.echo(f"HTTPX request failed: {e}")


if __name__ == "__main__":
    cli()
