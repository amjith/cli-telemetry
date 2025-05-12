"""
Instrumentation for subprocess.run to auto-wrap calls in telemetry spans.
"""

import os
import time

from ..telemetry import Span, add_tags


def auto_instrument_subprocess():
    """Monkeypatch subprocess.run to auto-wrap calls in telemetry spans."""
    # Allow opt-out via environment variable
    if os.environ.get("CLI_TELEMETRY_DISABLE_SUBPROCESS_PATCH") == "1":
        return

    try:
        import subprocess
    except ImportError:
        return  # subprocess not available, skip instrumentation

    # Avoid double-patching
    if getattr(subprocess, "_telemetry_patched", False):
        return

    original_run = subprocess.run

    def run_with_span(*args, **kwargs):
        # args[0] or kwargs['args'] holds the command
        cmd = args[0] if args else kwargs.get("args")
        start = time.time()
        with Span("subprocess.run"):
            # Record the command
            add_tags({"subprocess.command": cmd})
            try:
                result = original_run(*args, **kwargs)
                rc = getattr(result, "returncode", None)
                add_tags({"subprocess.exit_code": rc})
                return result
            except Exception as exc:
                # Capture exit code if available
                rc = getattr(exc, "returncode", None)
                add_tags({"subprocess.exit_code": rc})
                raise
            finally:
                elapsed_ms = int((time.time() - start) * 1000)
                add_tags({"subprocess.duration_ms": elapsed_ms})

    subprocess.run = run_with_span
    subprocess._telemetry_patched = True
