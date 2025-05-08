"""
Instrumentation for HTTPX requests to auto-wrap them in telemetry spans.
"""

import os
import time

from ..telemetry import Span, add_tag


def auto_instrument_httpx():
    """Monkeypatch httpx.Client and httpx.AsyncClient to auto-wrap HTTP calls in telemetry spans."""
    # Allow opt-out via environment variable
    if os.environ.get("CLI_TELEMETRY_DISABLE_HTTPX_PATCH") == "1":
        return

    try:
        import httpx
    except ImportError:
        return  # httpx not installed, skip instrumentation

    # Instrument sync Client.request
    if hasattr(httpx, "Client") and not getattr(httpx.Client, "_telemetry_patched", False):
        original_request = httpx.Client.request

        def request_with_span(self, method, url, *args, **kwargs):
            start = time.time()
            with Span("httpx.request"):
                add_tag("http.method", method)
                add_tag("http.url", str(url))
                response = original_request(self, method, url, *args, **kwargs)
                # Capture status code
                try:
                    status = response.status_code
                except Exception:
                    status = None
                add_tag("http.status_code", status)
                # Capture latency in milliseconds
                elapsed_ms = int((time.time() - start) * 1000)
                add_tag("http.latency_ms", elapsed_ms)
                return response

        httpx.Client.request = request_with_span
        httpx.Client._telemetry_patched = True

    # Instrument async AsyncClient.request
    if hasattr(httpx, "AsyncClient") and not getattr(httpx.AsyncClient, "_telemetry_patched", False):
        original_async_request = httpx.AsyncClient.request

        async def async_request_with_span(self, method, url, *args, **kwargs):
            start = time.time()
            with Span("httpx.request"):
                add_tag("http.method", method)
                add_tag("http.url", str(url))
                response = await original_async_request(self, method, url, *args, **kwargs)
                # Capture status code
                try:
                    status = response.status_code
                except Exception:
                    status = None
                add_tag("http.status_code", status)
                # Capture latency in milliseconds
                elapsed_ms = int((time.time() - start) * 1000)
                add_tag("http.latency_ms", elapsed_ms)
                return response

        httpx.AsyncClient.request = async_request_with_span
        httpx.AsyncClient._telemetry_patched = True
