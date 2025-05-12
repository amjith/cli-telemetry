"""
Upload plugin for homegrown remote trace ingestion.
"""

import json
import urllib.request
import urllib.error

import click

from cli_telemetry.telemetry import read_spans


def register(cli):
    """Register the 'upload' command to push traces to a remote server."""

    @cli.command(name="upload")
    @click.option("--db-file", default=None, help="Path to telemetry.db file (overrides config)")
    @click.option("--trace-id", "trace_id", required=True, help="Trace ID to upload")
    @click.option("--server-url", default=None, help="Remote server URL to POST traces (overrides config)")
    @click.option(
        "--auth-token", envvar="CLI_TELEMETRY_UPLOAD_TOKEN", default=None, help="Bearer token for authentication (overrides config)"
    )
    @click.option("--timeout", default=None, type=int, help="Request timeout in seconds (overrides config)")
    @click.pass_context
    def upload(ctx, db_file, trace_id, server_url, auth_token, timeout):
        """Upload a trace to a remote server in JSON format."""
        # Load merged config (global + any tables, with local overrides)
        cfg = ctx.obj.get("config", {}) or {}
        # upload-specific overrides in [upload]
        upload_cfg = cfg.get("upload", {}) if isinstance(cfg.get("upload"), dict) else {}
        # global-level settings: top-level non-dict entries
        global_cfg = {k: v for k, v in cfg.items() if not isinstance(v, dict)}

        # Resolve settings: CLI flag > upload section > global section
        db_file = db_file or upload_cfg.get("db_file") or global_cfg.get("db_file")
        server_url = server_url or upload_cfg.get("server_url") or global_cfg.get("server_url")
        auth_token = auth_token or upload_cfg.get("auth_token") or global_cfg.get("auth_token")
        # Timeout: use CLI flag if set, else upload.timeout, else global.timeout, else default=10
        if timeout is None:
            t_val = upload_cfg.get("timeout", global_cfg.get("timeout"))
            try:
                timeout = int(t_val)
            except Exception:
                timeout = 10
        # Validate required values
        if not db_file:
            click.echo("Error: telemetry DB path not set (flag or config)", err=True)
            ctx.exit(1)
        if not server_url:
            click.echo("Error: server_url not set (flag or config)", err=True)
            ctx.exit(1)

        # Read raw spans from local DB
        spans = read_spans(db_file, trace_id)
        payload = {"trace_id": trace_id, "spans": spans}
        data = json.dumps(payload).encode("utf-8")
        # Prepare HTTP request
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        req = urllib.request.Request(server_url, data=data, headers=headers, method="POST")
        # Send request
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                click.echo(f"Uploaded trace {trace_id}: HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            click.echo(f"HTTP error: {e.code} {e.reason}", err=True)
            ctx.exit(1)
        except Exception as e:
            click.echo(f"Failed to upload: {e}", err=True)
            ctx.exit(1)
