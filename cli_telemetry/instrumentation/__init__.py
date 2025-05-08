"""
Automatic instrumentation registry for supported libraries.
"""

import os

from .click import auto_instrument_click


def init_auto_instrumentation() -> None:
    """
    Initialize automatic instrumentation for all supported libraries.
    Future instrumentation modules should be added here.
    """
    # Click instrumentation
    if "CLI_TELEMETRY_DISABLE_CLICK_INSTRUMENTATION" not in os.environ:
        try:
            auto_instrument_click()
        except Exception:
            pass

    # HTTPX instrumentation
    from .httpx import auto_instrument_httpx

    if "CLI_TELEMETRY_DISABLE_HTTPX_INSTRUMENTATION" not in os.environ:
        try:
            auto_instrument_httpx()
        except Exception:
            pass
