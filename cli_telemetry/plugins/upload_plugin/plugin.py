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
    @cli.command(name='upload')
    @click.option(
        '--db-file', required=True,
        help='Path to telemetry.db file'
    )
    @click.option(
        '--trace-id', 'trace_id', required=True,
        help='Trace ID to upload'
    )
    @click.option(
        '--server-url', required=True,
        help='Remote server URL to POST traces'
    )
    @click.option(
        '--auth-token', envvar='CLI_TELEMETRY_UPLOAD_TOKEN', default=None,
        help='Bearer token for authentication'
    )
    @click.option(
        '--timeout', default=10, type=int,
        help='Request timeout in seconds'
    )
    def upload(db_file, trace_id, server_url, auth_token, timeout):
        """Upload a trace to a remote server in JSON format."""
        # Read raw spans from local DB
        spans = read_spans(db_file, trace_id)
        payload = {'trace_id': trace_id, 'spans': spans}
        data = json.dumps(payload).encode('utf-8')
        # Prepare HTTP request
        headers = {'Content-Type': 'application/json'}
        if auth_token:
            headers['Authorization'] = f'Bearer {auth_token}'
        req = urllib.request.Request(
            server_url,
            data=data,
            headers=headers,
            method='POST'
        )
        # Send request
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                click.echo(f'Uploaded trace {trace_id}: HTTP {resp.status}')
        except urllib.error.HTTPError as e:
            click.echo(f'HTTP error: {e.code} {e.reason}', err=True)
            raise SystemExit(1)
        except Exception as e:
            click.echo(f'Failed to upload: {e}', err=True)
            raise SystemExit(1)
