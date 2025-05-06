from time import sleep
import click
from cli_telemetry.telemetry import start_session, end_session, profile, add_tag, profile_block


@click.group()
@click.pass_context
def cli(ctx):
    """
    Example CLI with telemetry instrumentation.
    """
    # Start the root span for this invocation
    cmd = ctx.invoked_subcommand or "cli"
    start_session(command_name=cmd, service_name="example-cli")
    # Ensure we end the span when the CLI exits
    ctx.call_on_close(end_session)


@cli.command()
@click.argument("message")
@profile
def echo(message):
    """Prints the message as-is."""
    # Tag the argument so it shows up on this span
    add_tag("args.message", message)
    click.echo(message)


@cli.command()
@click.argument("message")
@click.option("--times", "-n", default=1, show_default=True, help="How many times to shout")
@profile
def shout(message, times):
    """Prints the message uppercased with exclamation."""
    add_tag("args.message", message)
    add_tag("args.times", times)
    for _ in range(times):
        click.echo(f"{message.upper()}!")


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
