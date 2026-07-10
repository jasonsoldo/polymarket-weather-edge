import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .monitor import build_live_snapshot


def read_recent_snapshots(log_path: str, limit: int = 20) -> list[dict]:
    path = Path(log_path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    snapshots = []
    for line in lines:
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            snapshots.append({"error": "invalid jsonl row", "raw": line})
    return snapshots


def render_dashboard(snapshot: dict, history: list[dict]) -> str:
    action = snapshot.get("recommended_action", "UNKNOWN")
    risk_reasons = snapshot.get("risk_reasons", [])
    weather = snapshot.get("weather", {})
    markets = snapshot.get("markets", [])
    rows = []
    for market in markets[:20]:
        rows.append(
            "<tr>"
            f"<td>{_esc(market.get('market_id', ''))}</td>"
            f"<td>{_esc(market.get('question', ''))}</td>"
            f"<td>{_esc(market.get('market_type_guess', ''))}</td>"
            f"<td>{_esc(market.get('excluded_reason', ''))}</td>"
            f"<td>{_esc(market.get('city_match_score', ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='5'>No strict city temperature markets found.</td></tr>")

    history_rows = []
    for item in reversed(history[-20:]):
        history_rows.append(
            "<tr>"
            f"<td>{_esc(item.get('observed_at', ''))}</td>"
            f"<td>{_esc(item.get('recommended_action', ''))}</td>"
            f"<td>{_esc(item.get('markets_found', ''))}</td>"
            f"<td>{_esc(item.get('reason', ''))}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>WeatherEdge Monitor</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #18212f; background: #f7f8fa; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .card {{ background: white; border: 1px solid #d9dee7; border-radius: 8px; padding: 14px; }}
    .status {{ font-size: 28px; font-weight: 700; }}
    .NO_TRADE {{ color: #b42318; }}
    .WATCH {{ color: #067647; }}
    .NO_MARKET {{ color: #6941c6; }}
    table {{ width: 100%; border-collapse: collapse; background: white; margin-top: 12px; }}
    th, td {{ border: 1px solid #d9dee7; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef2f7; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #101828; color: #f9fafb; padding: 12px; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>WeatherEdge Monitor</h1>
  <div class="grid">
    <div class="card"><div>Action</div><div class="status {action}">{_esc(action)}</div></div>
    <div class="card"><div>City</div><strong>{_esc(snapshot.get('city', ''))}</strong></div>
    <div class="card"><div>Date</div><strong>{_esc(snapshot.get('target_date', ''))}</strong></div>
    <div class="card"><div>Markets Found</div><strong>{_esc(snapshot.get('markets_found', 0))}</strong></div>
    <div class="card"><div>Disagreement</div><strong>{_esc(weather.get('disagreement', ''))}</strong></div>
    <div class="card"><div>Confidence</div><strong>{_esc(weather.get('confidence', ''))}</strong></div>
  </div>

  <h2>Risk</h2>
  <pre>{_esc(json.dumps({'blocked_by': snapshot.get('blocked_by', ''), 'risk_reasons': risk_reasons, 'threshold': snapshot.get('threshold', {})}, indent=2))}</pre>

  <h2>Markets</h2>
  <table>
    <tr><th>Market ID</th><th>Question</th><th>Type</th><th>Excluded</th><th>City Score</th></tr>
    {''.join(rows)}
  </table>

  <h2>Recent Snapshots</h2>
  <table>
    <tr><th>Observed At</th><th>Action</th><th>Markets</th><th>Reason</th></tr>
    {''.join(history_rows)}
  </table>

  <h2>Raw Snapshot</h2>
  <pre>{_esc(json.dumps(snapshot, indent=2, sort_keys=True))}</pre>
</body>
</html>"""


def run_web_monitor(
    host: str,
    port: int,
    city: str,
    latitude: float,
    longitude: float,
    target_date: str,
    log_path: str = "logs/live_monitor.jsonl",
    market_limit: int = 100,
    pages: int = 3,
    include_broad_weather: bool = False,
) -> None:
    handler = _make_handler(city, latitude, longitude, target_date, log_path, market_limit, pages, include_broad_weather)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"WeatherEdge web monitor listening on http://{host}:{port}")
    server.serve_forever()


def _make_handler(
    city: str,
    latitude: float,
    longitude: float,
    target_date: str,
    log_path: str,
    market_limit: int,
    pages: int,
    include_broad_weather: bool,
):
    class WebMonitorHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"ok": True})
                return
            if parsed.path == "/api/logs":
                limit = int(parse_qs(parsed.query).get("limit", ["20"])[0])
                self._send_json({"snapshots": read_recent_snapshots(log_path, limit)})
                return
            if parsed.path == "/api/snapshot":
                self._send_json(self._snapshot())
                return
            if parsed.path == "/":
                snapshot = self._snapshot()
                body = render_dashboard(snapshot, read_recent_snapshots(log_path, 20)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def log_message(self, format, *args):
            return

        def _snapshot(self):
            return build_live_snapshot(
                city,
                latitude,
                longitude,
                target_date,
                market_limit=market_limit,
                pages=pages,
                include_broad_weather=include_broad_weather,
            )

        def _send_json(self, payload: dict):
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return WebMonitorHandler


def _esc(value) -> str:
    return html.escape(str(value), quote=True)
