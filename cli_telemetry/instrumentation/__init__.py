import logging

from .instrument_click import auto_instrument_click
from .instrument_httpx import auto_instrument_httpx

logger = logging.getLogger(__name__)

def init_auto_instrumentation() -> None:
    """
    Initialize automatic instrumentation for all supported libraries.
    Future instrumentation modules should be added here.
    """
    # Click instrumentation
    try:
        auto_instrument_click()
    except Exception:
        logger.exception("Failed to instrument Click commands.")
        pass

    try:
        auto_instrument_httpx()
    except Exception:
        logger.exception("Failed to instrument HTTPX requests.")
        pass
