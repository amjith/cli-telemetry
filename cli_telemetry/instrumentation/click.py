"""
Instrumentation for Click commands to auto-wrap their invocation in telemetry spans.
"""

from ..telemetry import Span, add_tag


def auto_instrument_click():
    """Monkeypatch click.Command and click.Group to auto-wrap in telemetry spans."""
    import os

    if os.environ.get("CLI_TELEMETRY_DISABLE_CLICK_PATCH") == "1":
        return  # User has opted out of monkeypatching

    try:
        import click

        def telemetry_wrapper(original_invoke):
            def invoke_with_span(self, ctx):
                # Assumes init_telemetry() already called by app
                with Span(self.name, attributes={"cli.command": ctx.command_path}):
                    try:
                        for param in self.params:
                            if param.name in ctx.params:
                                add_tag(f"args.{param.name}", ctx.params[param.name])
                    except Exception:
                        pass
                    return original_invoke(self, ctx)

            return invoke_with_span

        # Avoid double-patching
        if not getattr(click.Command, "_telemetry_patched", False):
            click.Command.invoke = telemetry_wrapper(click.Command.invoke)
            click.Command._telemetry_patched = True

        if not getattr(click.Group, "_telemetry_patched", False):
            click.Group.invoke = telemetry_wrapper(click.Group.invoke)
            click.Group._telemetry_patched = True

    except ImportError:
        pass  # No click? No telemetry sadness.
