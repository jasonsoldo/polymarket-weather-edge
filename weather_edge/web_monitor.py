import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .monitor import build_all_cities_snapshot, build_live_snapshot


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
    if snapshot.get("mode") == "all_cities":
        return render_all_cities_dashboard(snapshot, history)

    action = snapshot.get("recommended_action", "UNKNOWN")
    risk_reasons = snapshot.get("risk_reasons", [])
    weather = snapshot.get("weather", {})
    bucket_rows = []
    for bucket in _event_bucket_rows(snapshot):
        death_gap = "YES" if bucket["death_gap"] else ""
        bucket_rows.append(
            "<tr>"
            f"<td>{_esc(bucket['event'])}</td>"
            f"<td>{_esc(bucket['bucket'])}</td>"
            f"<td>{_esc(bucket['price'])}</td>"
            f"<td>{_esc(bucket['model_probability'])}</td>"
            f"<td>{_esc(bucket['edge'])}</td>"
            f"<td>{_esc(bucket['shares'])}</td>"
            f"<td>{_esc(bucket['pnl_if_wins'])}</td>"
            f"<td>{_esc(death_gap)}</td>"
            f"<td>{_esc(bucket['action'])}</td>"
            "</tr>"
        )
    if not bucket_rows:
        bucket_rows.append("<tr><td colspan='9'>No analyzable city temperature buckets found.</td></tr>")

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

  <h2>Temperature Buckets</h2>
  <table>
    <tr><th>Event</th><th>Bucket</th><th>Price</th><th>Model Probability</th><th>Edge</th><th>Shares</th><th>PnL If Wins</th><th>Death Gap</th><th>Action</th></tr>
    {''.join(bucket_rows)}
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


def render_all_cities_dashboard(snapshot: dict, history: list[dict]) -> str:
    action = snapshot.get("recommended_action", "UNKNOWN")
    city_rows = []
    for item in snapshot.get("cities", []):
        weather = item.get("weather", {})
        city_rows.append(
            "<tr>"
            f"<td>{_esc(item.get('city', ''))}</td>"
            f"<td>{_esc(item.get('recommended_action', ''))}</td>"
            f"<td>{_esc(item.get('markets_found', 0))}</td>"
            f"<td>{_esc(weather.get('disagreement', ''))}</td>"
            f"<td>{_esc(weather.get('confidence', ''))}</td>"
            f"<td>{_esc(', '.join(item.get('risk_reasons', [])))}</td>"
            "</tr>"
        )
    if not city_rows:
        city_rows.append("<tr><td colspan='6'>No cities configured.</td></tr>")

    bucket_rows = []
    for item in snapshot.get("cities", []):
        for bucket in _event_bucket_rows(item):
            bucket_rows.append(
                "<tr>"
                f"<td>{_esc(item.get('city', ''))}</td>"
                f"<td>{_esc(bucket['event'])}</td>"
                f"<td>{_esc(bucket['bucket'])}</td>"
                f"<td>{_esc(bucket['price'])}</td>"
                f"<td>{_esc(bucket['model_probability'])}</td>"
                f"<td>{_esc(bucket['edge'])}</td>"
                f"<td>{_esc(bucket['pnl_if_wins'])}</td>"
                f"<td>{_esc('YES' if bucket['death_gap'] else '')}</td>"
                f"<td>{_esc(bucket['action'])}</td>"
                "</tr>"
            )
    if not bucket_rows:
        bucket_rows.append("<tr><td colspan='9'>No analyzable city temperature buckets found.</td></tr>")

    market_rows = []
    for market in snapshot.get("strict_markets", [])[:50]:
        market_rows.append(
            "<tr>"
            f"<td>{_esc(market.get('city_guess', ''))}</td>"
            f"<td>{_esc(market.get('market_id', ''))}</td>"
            f"<td>{_esc(market.get('question', ''))}</td>"
            f"<td>{_esc(market.get('market_type_guess', ''))}</td>"
            f"<td>{_esc(market.get('matched_keywords', ''))}</td>"
            "</tr>"
        )
    if not market_rows:
        market_rows.append("<tr><td colspan='5'>No strict temperature markets found globally.</td></tr>")

    history_rows = []
    for item in reversed(history[-20:]):
        history_rows.append(
            "<tr>"
            f"<td>{_esc(item.get('observed_at', ''))}</td>"
            f"<td>{_esc(item.get('recommended_action', ''))}</td>"
            f"<td>{_esc(item.get('markets_found', ''))}</td>"
            f"<td>{_esc(item.get('cities_monitored', ''))}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>WeatherEdge All Cities Monitor</title>
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
  <h1>WeatherEdge All Cities Monitor</h1>
  <div class="grid">
    <div class="card"><div>Action</div><div class="status {action}">{_esc(action)}</div></div>
    <div class="card"><div>Date</div><strong>{_esc(snapshot.get('target_date', ''))}</strong></div>
    <div class="card"><div>Cities</div><strong>{_esc(snapshot.get('cities_monitored', 0))}</strong></div>
    <div class="card"><div>City Markets</div><strong>{_esc(snapshot.get('markets_found', 0))}</strong></div>
    <div class="card"><div>Global Strict Markets</div><strong>{_esc(snapshot.get('strict_markets_found', 0))}</strong></div>
  </div>

  <h2>Cities</h2>
  <table>
    <tr><th>City</th><th>Action</th><th>Markets</th><th>Disagreement</th><th>Confidence</th><th>Reasons</th></tr>
    {''.join(city_rows)}
  </table>

  <h2>City Temperature Buckets</h2>
  <table>
    <tr><th>City</th><th>Event</th><th>Bucket</th><th>Price</th><th>Model Probability</th><th>Edge</th><th>PnL If Wins</th><th>Death Gap</th><th>Action</th></tr>
    {''.join(bucket_rows)}
  </table>

  <h2>Global Strict Temperature Markets</h2>
  <table>
    <tr><th>City Guess</th><th>Market ID</th><th>Question</th><th>Type</th><th>Matched Keywords</th></tr>
    {''.join(market_rows)}
  </table>

  <h2>Recent Snapshots</h2>
  <table>
    <tr><th>Observed At</th><th>Action</th><th>Markets</th><th>Cities</th></tr>
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


def run_all_cities_web_monitor(
    host: str,
    port: int,
    target_date: str,
    log_path: str = "logs/live_monitor_all.jsonl",
    market_limit: int = 100,
    pages: int = 3,
    include_broad_weather: bool = False,
) -> None:
    handler = _make_all_cities_handler(target_date, log_path, market_limit, pages, include_broad_weather)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"WeatherEdge all-cities web monitor listening on http://{host}:{port}")
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


def _make_all_cities_handler(
    target_date: str,
    log_path: str,
    market_limit: int,
    pages: int,
    include_broad_weather: bool,
):
    class AllCitiesWebMonitorHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"ok": True, "mode": "all_cities"})
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
            return build_all_cities_snapshot(
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

    return AllCitiesWebMonitorHandler


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _event_bucket_rows(snapshot: dict) -> list[dict]:
    rows = []
    for event in snapshot.get("markets", []):
        plan = event.get("event_bucket_plan") or {}
        curve = plan.get("curve") or {}
        death_gaps = {gap.get("bucket", "") for gap in curve.get("death_gaps", [])}
        action = (plan.get("decision") or {}).get("recommended_action", "")
        for bucket in curve.get("rows", []):
            rows.append(
                {
                    "event": event.get("event_slug") or event.get("event_id", ""),
                    "bucket": bucket.get("bucket", ""),
                    "price": bucket.get("price", ""),
                    "model_probability": bucket.get("model_probability", ""),
                    "edge": bucket.get("edge", ""),
                    "shares": bucket.get("shares", ""),
                    "pnl_if_wins": bucket.get("pnl_if_wins", ""),
                    "death_gap": bucket.get("bucket", "") in death_gaps,
                    "action": action,
                }
            )
    return rows
