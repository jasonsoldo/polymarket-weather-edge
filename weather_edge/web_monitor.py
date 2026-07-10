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
    return _render_monitor(snapshot, "WeatherEdge Monitor")


def render_all_cities_dashboard(snapshot: dict, history: list[dict]) -> str:
    return _render_monitor(snapshot, "WeatherEdge All Cities Monitor")


def _render_monitor(snapshot: dict, title: str) -> str:
    action = snapshot.get("recommended_action", "UNKNOWN")
    rows = _monitor_rows(snapshot)
    rendered_rows = [
        "<tr>"
        f"<td>{_esc(row['city'])}</td><td>{_esc(row['market'])}</td><td>{_esc(row['settlement'])}</td>"
        f"<td>{_esc(row['weather'])}</td><td>{_esc(row['model_temperature'])}</td>"
        f"<td>{_esc(row['capital_limit'])}</td><td>{_esc(row['investment'])}</td>"
        f"<td>{_esc(row['profit'])}</td><td>{_esc(row['loss'])}</td><td>{_esc(row['action'])}</td>"
        "</tr>"
        for row in rows
    ] or ["<tr><td colspan='10'>No analyzable real city temperature markets found.</td></tr>"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30"><title>{_esc(title)}</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;color:#18212f;background:#f7f8fa}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}.card,table{{background:#fff;border:1px solid #d9dee7;border-radius:8px}}.card{{padding:14px}}.status{{font-size:26px;font-weight:700}}.NO_TRADE{{color:#b42318}}.WATCH{{color:#067647}}.NO_MARKET{{color:#6941c6}}table{{width:100%;border-collapse:collapse;margin-top:12px}}th,td{{border:1px solid #d9dee7;padding:8px;text-align:left;vertical-align:top}}th{{background:#eef2f7}}</style></head>
<body><h1>{_esc(title)}</h1><div class="grid"><div class="card">Action<div class="status {action}">{_esc(action)}</div></div><div class="card">Date<br><strong>{_esc(snapshot.get('target_date',''))}</strong></div><div class="card">Cities<br><strong>{_esc(snapshot.get('cities_monitored', 1))}</strong></div><div class="card">Real Markets<br><strong>{_esc(snapshot.get('markets_found',0))}</strong></div></div>
<h2>Real Weather Market Monitor</h2><table><tr><th>City</th><th>Market</th><th>Settlement</th><th>Real Weather</th><th>Model Temp</th><th>Capital Limit</th><th>Planned Investment</th><th>Potential Profit</th><th>Maximum Loss</th><th>Action</th></tr>{''.join(rendered_rows)}</table></body></html>"""


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


def _monitor_rows(snapshot: dict) -> list[dict]:
    rows = []
    city_snapshots = snapshot.get("cities", [snapshot])
    for city_snapshot in city_snapshots:
        weather = _weather_summary(city_snapshot.get("weather") or {})
        for event in city_snapshot.get("markets", []):
            plan = event.get("event_bucket_plan") or {}
            curve = plan.get("curve") or {}
            rule = plan.get("settlement_rule") or {}
            model = plan.get("forecast_model") or {}
            market = (event.get("markets") or [{}])[0]
            first_bucket = (curve.get("rows") or [{}])[0].get("bucket", "")
            rows.append(
                {
                    "city": city_snapshot.get("city", ""),
                    "market": market.get("question") or f"{event.get('event_slug', '')} {first_bucket}".strip(),
                    "settlement": " | ".join(item for item in (rule.get("settlement_source", ""), rule.get("target_station_or_data_source", ""), rule.get("measurement_unit", "")) if item),
                    "weather": weather,
                    "model_temperature": _model_temperature(model, rule.get("measurement_unit", "")),
                    "capital_limit": _number(snapshot.get("risk_capital_limit", city_snapshot.get("risk_capital_limit", 0))),
                    "investment": _number(curve.get("total_cost", 0)),
                    "profit": _number(max(0.0, curve.get("best_case_pnl", 0))),
                    "loss": _number(max(0.0, -curve.get("worst_case_pnl", 0))),
                    "action": (plan.get("decision") or {}).get("recommended_action", city_snapshot.get("recommended_action", "")),
                }
            )
    return rows


def _weather_summary(weather: dict) -> str:
    forecasts = []
    for forecast in weather.get("forecasts", []):
        unit = forecast.get("unit", "")
        forecasts.append(f"{forecast.get('source', '')}: H {forecast.get('max_temp', '')}{unit} / L {forecast.get('min_temp', '')}{unit}")
    return " | ".join(forecasts)


def _model_temperature(model: dict, unit: str) -> str:
    if "mean" not in model:
        return ""
    return f"{_number(model['mean'])}{unit} +/- {_number(model.get('standard_deviation', 0))}"


def _number(value) -> str:
    return f"{float(value):.2f}"
