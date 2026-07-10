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
    portfolio = snapshot.get("portfolio") or {}
    rows = _monitor_rows(snapshot)
    rendered_rows = [
        "<tr>"
        f"<td><strong>{_esc(row['city'])}</strong><br><span class='muted'>{_esc(row['normalized_city'])} | {_esc(row['station_code'])} | {_esc(row['registry_status'])}</span></td>"
        f"<td><strong>{_esc(row['market'])}</strong><br><span class='muted'>{_esc(row['settlement'])}</span></td>"
        f"<td>{_esc(row['weather'])}<br><span class='model'>{_esc(row['model_temperature'])}</span></td>"
        f"<td>{_esc(row['investment'])}<br><span class='muted'>cap { _esc(row['capital_limit']) }</span></td>"
        f"<td class='positive'>{_esc(row['profit'])}</td><td class='negative'>{_esc(row['loss'])}</td>"
        f"<td><span class='badge { _esc(row['action']) }'>{_esc(row['action'])}</span></td>"
        "</tr>"
        for row in rows
    ] or ["<tr><td colspan='7'>No analyzable real city temperature markets found.</td></tr>"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="30"><title>{_esc(title)}</title>
<style>:root{{color:#172033;background:#f4f7fb;font-family:Arial,sans-serif}}*{{box-sizing:border-box}}body{{margin:0;background:#f4f7fb}}main{{max-width:1480px;margin:auto;padding:26px}}header{{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:20px}}h1{{font-size:24px;margin:0}}h2{{font-size:16px;margin:26px 0 10px}}.sub,.muted{{color:#667085;font-size:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px}}.card{{background:#fff;border:1px solid #d9e1ec;border-radius:8px;padding:13px;min-height:82px}}.metric{{font-size:22px;font-weight:700;margin-top:8px}}.positive{{color:#067647;font-weight:700}}.negative{{color:#b42318;font-weight:700}}.status.NO_TRADE{{color:#b42318}}.status.WATCH{{color:#067647}}.status.NO_MARKET{{color:#6941c6}}.table-wrap{{overflow:auto;border:1px solid #d9e1ec;border-radius:8px;background:#fff}}table{{width:100%;min-width:920px;border-collapse:collapse}}th,td{{padding:12px;border-bottom:1px solid #e8edf3;text-align:left;vertical-align:top;font-size:13px;line-height:1.45}}th{{background:#f8fafc;color:#475467;font-size:11px;text-transform:uppercase;letter-spacing:.04em;position:sticky;top:0}}tr:last-child td{{border-bottom:0}}.model{{display:block;color:#175cd3;font-size:12px;margin-top:4px}}.badge{{display:inline-block;border-radius:999px;padding:4px 8px;background:#eef2f7;color:#344054;font-size:11px;font-weight:700}}.badge.exit_positions,.badge.block_new_position,.badge.NO_TRADE{{background:#fef3f2;color:#b42318}}.badge.allow_with_limit_order_and_duplicate_guard,.badge.WATCH{{background:#ecfdf3;color:#067647}}@media(max-width:640px){{main{{padding:16px}}header{{align-items:start;flex-direction:column}}}}</style></head>
<body><main><header><div><h1>{_esc(title)}</h1><div class="sub">Real market, real weather, risk-gated simulation</div></div><div class="sub">Auto refresh: 30s | { _esc(snapshot.get('target_date','')) }</div></header>
<section class="grid"><div class="card">System action<div class="metric status {action}">{_esc(action)}</div></div><div class="card">Cities / markets<div class="metric">{_esc(snapshot.get('cities_monitored',1))} / {_esc(snapshot.get('markets_found',0))}</div></div><div class="card">Cost basis<div class="metric">{_esc(_number(portfolio.get('cost_basis',0)))}</div></div><div class="card">Marked value<div class="metric">{_esc(_number(portfolio.get('market_value',0)))}</div></div><div class="card">Unrealized PnL<div class="metric {'positive' if portfolio.get('unrealized_pnl',0) >= 0 else 'negative'}">{_esc(_number(portfolio.get('unrealized_pnl',0)))}</div></div><div class="card">Stale positions<div class="metric">{_esc(portfolio.get('stale_positions',0))}</div></div></section>
<h2>Discovery</h2><div class="sub">Scanned {_esc(snapshot.get('markets_scanned', 0))} markets | strict temperature {_esc(snapshot.get('temperature_markets_found', snapshot.get('strict_markets_found', 0)))} | cities {_esc(snapshot.get('cities_discovered', snapshot.get('cities_monitored', 0)))} | registered {_esc(snapshot.get('registered_cities', 0))} | unregistered {_esc(snapshot.get('unregistered_cities', 0))} | excluded {_esc(snapshot.get('excluded_markets', 0))} | pages {_esc(snapshot.get('pages_scanned', 0))} | completed {_esc(snapshot.get('scan_completed', False))}</div><h2>Real Weather Markets</h2><div class="table-wrap"><table><tr><th>Discovered city / source</th><th>Market / Settlement</th><th>Real Weather / Model</th><th>Investment</th><th>Potential Profit</th><th>Maximum Loss</th><th>Action</th></tr>{''.join(rendered_rows)}</table></div></main></body></html>"""


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
            observation = event.get("settlement_observation") or {}
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
                    "source_state": observation.get("status", plan.get("settlement_source_status", "")),
                    "normalized_city": city_snapshot.get("normalized_city", city_snapshot.get("city", "")),
                    "station_code": market.get("station_code", ""),
                    "registry_status": market.get("city_registry_status", city_snapshot.get("city_registry_status", "")),
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
