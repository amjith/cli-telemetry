"""
Plugin module containing the webapp implementation and registration.
"""
import os
import sqlite3
import json
import click
from flask import Flask, jsonify, request
from flask_cors import CORS

def create_app(db_file):
    """Create and configure the Flask application for the web UI."""
    static_folder = os.path.join(os.path.dirname(__file__), 'webapp_static')
    app = Flask(__name__, static_folder=static_folder, static_url_path='/static')
    CORS(app)

    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    @app.route('/api/users')
    def get_users():
        con = sqlite3.connect(db_file)
        cur = con.cursor()
        cur.execute("SELECT attributes FROM otel_spans")
        rows = cur.fetchall()
        users = set()
        for (attr_json,) in rows:
            try:
                attrs = json.loads(attr_json)
                uid = attrs.get('telemetry.user_id')
                if uid:
                    users.add(uid)
            except Exception:
                continue
        con.close()
        return jsonify(sorted(users))

    @app.route('/api/traces')
    def get_traces():
        user_id = request.args.get('user_id')
        con = sqlite3.connect(db_file)
        cur = con.cursor()
        cur.execute(
            "SELECT trace_id, MIN(start_time) AS ts"
            " FROM otel_spans"
            " GROUP BY trace_id"
            " ORDER BY ts DESC"
        )
        rows = cur.fetchall()
        traces = []
        for trace_id, ts in rows:
            if user_id:
                cur2 = con.execute(
                    "SELECT attributes FROM otel_spans WHERE trace_id=?", (trace_id,)
                )
                found = False
                for (rjson,) in cur2.fetchall():
                    try:
                        attrs = json.loads(rjson)
                        if attrs.get('telemetry.user_id') == user_id:
                            found = True
                            break
                    except Exception:
                        continue
                if not found:
                    continue
            traces.append({'trace_id': trace_id, 'start_time': ts})
            if user_id and len(traces) >= 10:
                break
        con.close()
        return jsonify(traces)

    @app.route('/api/spans')
    def get_spans():
        trace_id = request.args.get('trace_id')
        if not trace_id:
            return jsonify({'error': 'trace_id parameter is required'}), 400
        con = sqlite3.connect(db_file)
        cur = con.cursor()
        cur.execute(
            "SELECT span_id, parent_span_id, name, start_time, end_time, attributes, status_code"
            " FROM otel_spans"
            " WHERE trace_id=?"
            " ORDER BY start_time",
            (trace_id,)
        )
        rows = cur.fetchall()
        spans_by_id = {}
        for span_id, parent_id, name, start, end, attr_json, status_code in rows:
            try:
                attributes = json.loads(attr_json)
            except Exception:
                attributes = {}
            spans_by_id[span_id] = {
                'span_id': span_id,
                'parent_span_id': parent_id,
                'name': name,
                'start_time': start,
                'end_time': end,
                'attributes': attributes,
                'status_code': status_code,
                'children': []
            }
        roots = []
        for span in spans_by_id.values():
            parent_id = span['parent_span_id']
            if parent_id and parent_id in spans_by_id:
                spans_by_id[parent_id]['children'].append(span)
            else:
                roots.append(span)
        con.close()
        return jsonify(roots)

    return app

def register(cli):
    """Register the webapp command for serving the web-based viewer."""
    @cli.command()
    @click.option('--db-file', required=True, help='Path to telemetry.db file to load')
    @click.option('--host', default='127.0.0.1', help='Host to serve on')
    @click.option('--port', default=5000, type=int, help='Port to serve on')
    def webapp(db_file, host, port):
        """Serve the web-based telemetry viewer."""
        app = create_app(db_file)
        click.echo(f"Serving web UI on http://{host}:{port}")
        app.run(host=host, port=port)