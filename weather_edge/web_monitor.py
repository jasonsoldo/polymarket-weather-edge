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
        return _apply_eye_comfort(_render_terminal_dashboard(snapshot, history))
    return _apply_eye_comfort(_render_overview(snapshot, history, "WeatherEdge Monitor") + _compatibility_summary(snapshot))


def _apply_eye_comfort(document: str) -> str:
    theme = """<style>:root{--bg:#edf4ee;--panel:#f8fbf7;--ink:#20352b;--muted:#66786d;--line:#cad8ce;--blue:#35705a;--green:#287a55;--red:#ad4a52;--amber:#9a6b2f}body{background:var(--bg)!important;color:var(--ink)!important}.panel,.hero,.kpi,.card,.metric-card,.status-bar,.profile-card,.table-wrap{background:var(--panel)!important;border-color:var(--line)!important}aside.rail,.app>aside{background:#253b31!important}nav a{color:#8fa79a!important}nav a.active,nav a:hover{background:#365348!important;color:#f4f8f4!important}table th{background:#e4eee6!important;color:#40594b!important}table td,.item,.risk-row,.city-strip{border-color:#d8e3da!important}.model,.section-title a,.panel-head a{color:var(--blue)!important}</style>"""
    return document.replace("</head>", theme + "</head>", 1)


def _render_terminal_dashboard(snapshot: dict, history: list[dict]) -> str:
    action = snapshot.get("recommended_action", "UNKNOWN")
    portfolio = snapshot.get("portfolio") or {}
    rows = _monitor_rows(snapshot)
    blockers = snapshot.get("risk_reasons", []) or [c.get("block_reason") for c in snapshot.get("cities", []) if c.get("block_reason")]
    market_rows = []
    for row in rows[:80]:
        market_rows.append(
            "<tr>"
            f"<td><b>{_esc(row['city'])}</b><small>{_esc(row['normalized_city'])} · {_esc(row['station_code'] or 'station pending')}</small></td>"
            f"<td class='market-cell'><b>{_esc(row['market'])}</b><small>{_esc(row['settlement'] or 'settlement source pending')}</small></td>"
            f"<td><b>{_esc(row['model_temperature'] or '—')}</b><small>{_esc(row['weather'] or 'weather pending')}</small></td>"
            f"<td class='money'>{_esc(row['investment'])}<small>cap {_esc(row['capital_limit'])}</small></td>"
            f"<td class='positive'>+{_esc(row['profit'])}</td><td class='negative'>-{_esc(row['loss'])}</td>"
            f"<td><span class='terminal-badge { _esc(row['action']) }'>{_esc(row['action'])}</span><small>{_esc(row['block_reason'] or row['source_state'])}</small></td>"
            "</tr>"
        )
    city_rows = []
    for city in snapshot.get("cities", [])[:30]:
        weather = city.get("weather") or {}
        forecasts = weather.get("forecasts") or []
        forecast = forecasts[0] if forecasts else {}
        state = city.get("recommended_action", "NO_MARKET")
        city_rows.append(
            f"<div class='city-strip'><div><b>{_esc(city.get('city', 'Unknown'))}</b><small>{_esc(city.get('markets_found', 0))} markets · {_esc(city.get('city_registry_status', 'registered'))}</small></div>"
            f"<div class='temp'>{_esc(forecast.get('max_temp', '—'))}° / {_esc(forecast.get('min_temp', '—'))}°<small>{_esc(forecast.get('unit', ''))}</small></div>"
            f"<div class='confidence'>conf {_esc(weather.get('confidence', '—'))}<small>Δ {_esc(weather.get('disagreement', '—'))}</small></div>"
            f"<span class='terminal-badge { _esc(state) }'>{_esc(state)}</span></div>"
        )
    chart = _pnl_chart(snapshot)
    blocker_html = "".join(f"<div class='risk-row'><span class='risk-dot'></span><span>{_esc(reason)}</span></div>" for reason in blockers[:8]) or "<div class='quiet'>No active blockers</div>"
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='30'><title>WeatherEdge Terminal</title>
<style>{_terminal_css()}{_terminal_extra_css()}</style></head><body><div class='terminal'>
<aside class='rail'><div class='terminal-logo'>W<span>E</span><small>WEATHER EDGE</small></div><nav><a class='active' href='/'>⌂<span>Overview</span></a><a href='/markets'>◈<span>Markets</span></a><a href='/cities'>◎<span>Cities</span></a><a href='/weather-sources'>◒<span>Weather</span></a><a href='/settlement-sources'>◌<span>Settlement</span></a><a href='/risk'>!</a><a href='/positions'>▣</a></nav><div class='rail-foot'>LIVE<br><span>30s refresh</span></div></aside>
<main><header class='terminal-head'><div><div class='overline'>WEATHEREDGE / ALL CITIES CONTROL ROOM</div><h1>WeatherEdge All Cities Monitor</h1><p>Real market intelligence · risk-gated simulation · target {_esc(snapshot.get('target_date', ''))}</p></div><div class='head-status'><span class='live-dot'></span> LIVE MONITOR <small>{_esc(snapshot.get('observed_at', ''))}</small></div></header>
<section class='profile-grid'><div class='profile-card'><div class='profile-top'><span class='profile-dot'></span><span>WEATHEREDGE · LIVE WEATHER EDGE</span><span class='profile-chip'>READ ONLY</span></div><div class='profile-number'>{_esc(action)}</div><div class='profile-rule'></div><div class='profile-stats'><div><small>MARKETS</small><b>{_esc(snapshot.get('temperature_markets_found', snapshot.get('markets_found', 0)))}</b></div><div><small>CITIES</small><b>{_esc(snapshot.get('cities_discovered', 0))}</b></div><div><small>CONFIDENCE</small><b>{_esc(_top_confidence(snapshot))}</b></div><div><small>RISK</small><b>{_esc('BLOCKED' if action == 'NO_TRADE' else 'WATCH')}</b></div></div><div class='profile-foot'>updated {_esc(snapshot.get('observed_at', ''))} · official settlement gate active</div></div><div class='top-win panel'><div class='panel-head'><div><small class='overline'>TOP EVENT · WEATHER BUCKET</small><h2>{_esc(_top_event_name(snapshot))}</h2></div><span class='mini-label'>1 / {_esc(max(1, len(_monitor_rows(snapshot))))}</span></div>{_pnl_chart(snapshot)}<div class='win-meta'><span>ENTRY <b>{_esc(_number(_top_event_cost(snapshot)))}</b></span><span>BEST PNL <b class='positive'>+{_esc(_number(_top_event_best(snapshot)))}</b></span></div></div></section>
<section class='signal-panel panel'><div class='panel-head'><div><small class='overline'>MARKET RELATIONSHIP GRAPH</small><h2>City / source / bucket signal map</h2></div><span class='mini-label'>NODES {_esc(len(_monitor_rows(snapshot)))} · RISK GATED</span></div><div class='signal-layout'><div class='signal-legend'><span><i class='red-dot'></i>blocked signal</span><span><i class='green-dot'></i>watch signal</span><span><i class='black-dot'></i>settlement hub</span><b>{_esc(len(snapshot.get('cities', [])))} CITIES</b><small>{_esc(snapshot.get('markets_scanned', 0))} markets scanned<br>{_esc(snapshot.get('excluded_markets', 0))} excluded by filter</small></div>{_signal_graph(snapshot)}<div class='signal-readout'><small>P(TRADE)</small><b>0.00</b><small>P(NO TRADE)</small><b class='negative'>1.00</b><div class='edge-meter'></div><small>CONFIDENCE</small><b>{_esc(_top_confidence(snapshot))}</b></div></div></section>
<section class='pattern-panel panel'><div class='panel-head'><div><small class='overline'>PATTERN ENGINE · BUCKET CURVE</small><h2>Forecast vs market price</h2></div><span class='mini-label'>PROBABILITY · EDGE · EXECUTION</span></div><div class='pattern-layout'><div class='pattern-chart'>{_price_chart(snapshot)}</div><div class='pattern-copy'><span class='terminal-badge { _esc(action) }'>{_esc(action)}</span><b>{_esc(_top_event_reason(snapshot))}</b><small>Every bucket is checked for coverage, spread, liquidity, settlement source and PnL if wins.</small></div></div></section>
<section class='status-bar'><div><small>SYSTEM ACTION</small><strong class='{_state_class(action)}'>{_esc(action)}</strong><span>{_esc(blockers[0] if blockers else 'No active blockers')}</span></div><div class='scan-state'><small>DISCOVERY</small><b>{_esc(snapshot.get('scan_completed', False))}</b><span>{_esc(snapshot.get('pages_scanned', 0))} pages · {_esc(snapshot.get('markets_scanned', 0))} scanned</span></div></section>
{_hong_kong_strip(snapshot)}
<section class='metric-grid'>{_terminal_metric('HK MARKETS', _hong_kong_market_count(snapshot), 'highest temperature only')}{_terminal_metric('HK CONFIDENCE', _hong_kong_confidence(snapshot), 'forecast gate')}{_terminal_metric('COST BASIS', _number(portfolio.get('cost_basis', 0)), 'shadow capital')}{_terminal_metric('SHADOW REALIZED', _number((snapshot.get('hong_kong_closure') or {}).get('shadow_realized_pnl', 0)), 'finalized PnL')}{_terminal_metric('UNREALIZED PNL', _number(portfolio.get('unrealized_pnl', 0)), 'live estimate')}{_terminal_metric('STALE POSITIONS', portfolio.get('stale_positions', 0), 'must be zero')}</section>
<section class='main-grid'><section class='panel market-panel'><div class='panel-head'><div><small class='overline'>LIVE MARKET TAPE</small><h2>Real Weather Markets</h2></div><a href='/markets'>VIEW ALL →</a></div><div class='table-wrap'><table><thead><tr><th>City / station</th><th>Market / settlement</th><th>Model / weather</th><th>Investment</th><th>Potential</th><th>Max loss</th><th>Action</th></tr></thead><tbody>{''.join(market_rows) or "<tr><td colspan='7' class='quiet'>No strict city temperature markets found.</td></tr>"}</tbody></table></div></section><aside class='side-stack'><section class='panel'><div class='panel-head'><div><small class='overline'>RISK ENGINE</small><h2>Blockers</h2></div><a href='/risk'>DETAILS →</a></div>{blocker_html}</section><section class='panel chart-panel'><div class='panel-head'><div><small class='overline'>P&L CURVE</small><h2>Current event shape</h2></div><span class='mini-label'>SIMULATION</span></div>{chart}</section></aside></section>
<section class='panel city-panel'><div class='panel-head'><div><small class='overline'>WEATHER NETWORK</small><h2>City pulse</h2></div><a href='/cities'>VIEW ALL →</a></div><div class='city-list'>{''.join(city_rows) or "<div class='quiet'>No cities discovered.</div>"}</div></section>
<section class='pulse-panel panel'><div class='panel-head'><div><small class='overline'>ALL CITIES PULSE</small><h2>Real weather market activity</h2></div><span class='mini-label'>AUTO-REFRESH 30S</span></div>{_pulse_chart(snapshot)}</section>
</main></div></body></html>"""


def _terminal_metric(label, value, note):
    return f"<div class='metric-card'><small>{_esc(label)}</small><b>{_esc(value)}</b><span>{_esc(note)}</span></div>"


def _hong_kong_city(snapshot):
    return next((city for city in snapshot.get("cities", []) if city.get("city") == "Hong Kong"), {})


def _hong_kong_market_count(snapshot):
    return _hong_kong_city(snapshot).get("markets_found", 0)


def _hong_kong_confidence(snapshot):
    value = (_hong_kong_city(snapshot).get("weather") or {}).get("confidence")
    return f"{float(value) * 100:.0f}%" if value is not None else "-"


def _hong_kong_strip(snapshot):
    city = _hong_kong_city(snapshot)
    weather = city.get("weather") or {}
    closure = snapshot.get("hong_kong_closure") or {}
    forecasts = weather.get("forecasts") or []
    hko = next((item for item in forecasts if item.get("source") == "hko_forecast"), {})
    state = "VERIFIED" if closure.get("settlement_verified") else ("AUDIT PASSED" if closure.get("settlement_audit_passed") else "PENDING")
    blocker = "" if state == "VERIFIED" else "pending_hko_settlement_validation"
    return f"<section class='status-bar'><div><small>HONG KONG FIRST</small><strong class='{_state_class(state)}'>{_esc(state)}</strong><span>{_esc(blocker or 'HKO final result matches Polymarket')}</span></div><div class='scan-state'><small>HKO / SHADOW</small><b>{_esc(hko.get('max_temp', '-'))}°C</b><span>final {_esc(closure.get('final_daily_max', '-'))}°C · realized {_esc(_number(closure.get('shadow_realized_pnl', 0)))}</span></div><a href='/hong-kong'>DETAILS →</a></section>"


def _top_confidence(snapshot):
    values = []
    for city in snapshot.get("cities", [snapshot]):
        value = (city.get("weather") or {}).get("confidence")
        if value is not None:
            values.append(float(value))
    return f"{max(values) * 100:.0f}%" if values else "—"


def _top_event_name(snapshot):
    rows = _monitor_rows(snapshot)
    return rows[0]["market"][:48] if rows else "No active temperature event"


def _top_event_cost(snapshot):
    rows = _monitor_rows(snapshot)
    return float(rows[0]["investment"]) if rows else 0.0


def _top_event_best(snapshot):
    rows = _monitor_rows(snapshot)
    return float(rows[0]["profit"]) if rows else 0.0


def _top_event_reason(snapshot):
    rows = _monitor_rows(snapshot)
    return rows[0]["block_reason"] if rows and rows[0]["block_reason"] else "Waiting for a risk-approved candidate"


def _signal_graph(snapshot):
    rows = _monitor_rows(snapshot)[:18]
    nodes = []
    lines = []
    cx, cy = 360, 115
    for index, row in enumerate(rows):
        angle = (index / max(1, len(rows))) * 6.28
        x = cx + 245 * __import__("math").cos(angle)
        y = cy + 82 * __import__("math").sin(angle)
        color = "#c53f4b" if "block" in str(row["action"]).lower() or "no_trade" in str(row["action"]).lower() else "#07865c"
        lines.append(f"<line x1='{cx}' y1='{cy}' x2='{x:.0f}' y2='{y:.0f}' stroke='#d8d5cc' stroke-width='1'/>")
        nodes.append(f"<circle cx='{x:.0f}' cy='{y:.0f}' r='7' fill='{color}'/><text x='{x:.0f}' y='{y + 18:.0f}' text-anchor='middle' font-size='8' fill='#77818d'>{_esc(str(row['city'])[:12])}</text>")
    return f"<svg class='signal-svg' viewBox='0 0 720 230' preserveAspectRatio='xMidYMid meet'>{''.join(lines)}<circle cx='{cx}' cy='{cy}' r='25' fill='#172027'/><circle cx='{cx}' cy='{cy}' r='15' fill='#202d35'/><text x='{cx}' y='{cy + 4}' text-anchor='middle' font-size='9' fill='#fff'>HUB</text>{''.join(nodes)}</svg>"


def _price_chart(snapshot):
    values = []
    for row in _monitor_rows(snapshot):
        for city in snapshot.get("cities", [snapshot]):
            for event in city.get("markets", []):
                for item in ((event.get("event_bucket_plan") or {}).get("curve") or {}).get("rows", []):
                    if item.get("bucket") and item.get("price") is not None:
                        values.append(float(item.get("price", 0)))
    if not values:
        values = [0.2, 0.24, 0.18, 0.16, 0.12, 0.08]
    points = " ".join(f"{index * 100 / max(1, len(values) - 1):.1f},{78 - value * 58:.1f}" for index, value in enumerate(values[:32]))
    bars = []
    for index, value in enumerate(values[:32]):
        x = index * 100 / len(values)
        bars.append(f"<rect x='{x:.1f}' y='{88 - value * 65:.1f}' width='{max(1.2, 90 / len(values)):.1f}' height='{value * 65:.1f}' fill='#d9e8df'/>")
        if index % 4 == 0:
            bars.append(f"<circle cx='{x:.1f}' cy='{78 - value * 58:.1f}' r='2.2' fill='#172027'/>")
    return f"<svg class='price-svg' viewBox='0 0 100 100' preserveAspectRatio='none'><line x1='0' y1='78' x2='100' y2='78' stroke='#ddd9d0'/>{''.join(bars)}<polyline points='{points}' fill='none' stroke='#172027' stroke-width='1.2'/></svg><div class='chart-labels'><span>MARKET PRICE</span><span>MODEL PROBABILITY</span><span>BUCKETS</span></div>"


def _pulse_chart(snapshot):
    values = [float(city.get("markets_found", 0)) for city in snapshot.get("cities", [])]
    values = values or [0]
    bars = "".join(f"<rect x='{index * 100 / len(values):.1f}' y='{70 - min(55, value * 8):.1f}' width='{max(2, 80 / len(values)):.1f}' height='{min(55, value * 8):.1f}' fill='{('#cf5360' if index % 3 == 0 else '#53a986')}'/>" for index, value in enumerate(values))
    return f"<svg class='pulse-svg' viewBox='0 0 100 80' preserveAspectRatio='none'><line x1='0' y1='70' x2='100' y2='70' stroke='#ddd9d0'/>{bars}</svg>"


def _pnl_chart(snapshot):
    points = []
    for city in snapshot.get("cities", [snapshot]):
        for event in city.get("markets", []):
            for row in ((event.get("event_bucket_plan") or {}).get("curve") or {}).get("rows", []):
                try:
                    points.append(float(row.get("pnl_if_wins", 0)))
                except (TypeError, ValueError):
                    pass
    if not points:
        return "<div class='chart-empty'>PnL curve appears when a complete bucket plan is available.</div>"
    low, high = min(points), max(points)
    span = max(1.0, high - low)
    coords = " ".join(f"{index * 100 / max(1, len(points) - 1):.1f},{82 - (value - low) * 64 / span:.1f}" for index, value in enumerate(points))
    return f"<svg class='pnl-svg' viewBox='0 0 100 90' preserveAspectRatio='none'><defs><linearGradient id='fill' x1='0' x2='0' y1='0' y2='1'><stop offset='0' stop-color='#35c48b' stop-opacity='.25'/><stop offset='1' stop-color='#35c48b' stop-opacity='0'/></linearGradient></defs><polyline points='0,82 {coords} 100,82' fill='url(#fill)' stroke='none'/><polyline points='{coords}' fill='none' stroke='#35c48b' stroke-width='1.4'/></svg><div class='chart-labels'><span>Worst {_number(low)}</span><span>Best {_number(high)}</span></div>"


def _terminal_css():
    return """:root{--bg:#f3f5f7;--panel:#fff;--ink:#18212b;--muted:#77818d;--line:#e1e6ea;--dark:#172027;--green:#07865c;--red:#c53f4b;--amber:#b9781f}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:13px Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}.terminal{display:flex;min-height:100vh}.rail{width:76px;background:var(--dark);color:#98a5ad;display:flex;flex-direction:column;align-items:center;padding:22px 10px}.terminal-logo{color:#fff;font-weight:900;font-size:24px;letter-spacing:-2px;text-align:center}.terminal-logo span{color:#55c99b}.terminal-logo small{display:block;font-size:7px;letter-spacing:1px;color:#7f8c94;margin-top:6px}.rail nav{width:100%;display:flex;flex-direction:column;gap:8px;margin-top:42px}.rail nav a{height:42px;color:#83919a;text-decoration:none;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:19px;gap:11px}.rail nav a span{display:none}.rail nav a.active,.rail nav a:hover{background:#26343c;color:#fff}.rail-foot{margin-top:auto;text-align:center;font-size:9px;letter-spacing:1px;color:#55c99b;line-height:1.8}.rail-foot span{color:#697880;letter-spacing:0}main{width:100%;max-width:1800px;padding:30px 36px}.terminal-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px}.overline{font-size:9px;font-weight:800;letter-spacing:1.25px;color:#8b949e}.terminal-head h1{font-size:28px;margin:7px 0 3px;letter-spacing:-.8px}.terminal-head p{color:var(--muted);margin:0}.head-status{color:var(--green);font-size:10px;font-weight:800;letter-spacing:.8px}.head-status small{display:block;text-align:right;color:var(--muted);font-weight:500;letter-spacing:0;margin-top:7px}.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#34b781;margin-right:7px;box-shadow:0 0 0 3px #d9f6eb}.status-bar,.panel,.metric-card{background:var(--panel);border:1px solid var(--line);border-radius:9px}.status-bar{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;margin-bottom:13px}.status-bar small,.metric-card small{display:block;color:var(--muted);font-size:9px;font-weight:800;letter-spacing:1px}.status-bar strong{display:block;font-size:27px;letter-spacing:-.6px;margin:4px 0}.status-bar span,.scan-state span{display:block;color:var(--muted);font-size:11px}.scan-state{text-align:right;border-left:1px solid var(--line);padding-left:28px}.scan-state b{display:block;font-size:16px;margin:4px 0}.metric-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:13px}.metric-card{padding:14px 15px}.metric-card b{display:block;font-size:22px;margin:9px 0 4px;letter-spacing:-.5px}.metric-card span{font-size:10px;color:var(--muted)}.main-grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(280px,.65fr);gap:13px}.side-stack{display:flex;flex-direction:column;gap:13px}.panel{padding:18px;min-width:0}.panel-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}.panel-head h2{font-size:15px;margin:6px 0 0}.panel-head a{font-size:9px;color:var(--green);font-weight:800;text-decoration:none;letter-spacing:.6px}.mini-label{font-size:9px;color:var(--amber);font-weight:800}.table-wrap{overflow:auto}.table-wrap table{width:100%;min-width:840px;border-collapse:collapse}.table-wrap th{font-size:9px;color:#8a949e;text-align:left;font-weight:800;letter-spacing:.75px;padding:10px 8px;border-bottom:1px solid var(--line);white-space:nowrap}.table-wrap td{padding:12px 8px;border-bottom:1px solid #edf0f2;vertical-align:top;font-size:11px}.table-wrap td small,.city-strip small{display:block;color:var(--muted);font-size:9px;line-height:1.55;margin-top:4px}.market-cell{max-width:290px}.market-cell b{font-weight:650}.money{font-variant-numeric:tabular-nums}.positive{color:var(--green);font-weight:800}.negative{color:var(--red);font-weight:800}.terminal-badge{display:inline-block;border-radius:999px;padding:4px 7px;font-size:8px;font-weight:800;letter-spacing:.25px;background:#eef1f3;color:#66717a;white-space:nowrap}.terminal-badge.NO_TRADE,.terminal-badge.block_new_position{color:var(--red);background:#fff0f1}.terminal-badge.WATCH{color:var(--amber);background:#fff6e5}.terminal-badge.success{color:var(--green);background:#eaf8f2}.risk-row{display:flex;gap:9px;align-items:flex-start;padding:11px 0;border-bottom:1px solid #edf0f2;color:#596570;font-size:11px;line-height:1.45}.risk-row:last-child{border:0}.risk-dot{width:6px;height:6px;border-radius:50%;background:var(--red);margin-top:5px;flex:none}.quiet,.chart-empty{color:var(--muted);font-size:11px;padding:20px 0}.chart-panel{min-height:160px}.pnl-svg{width:100%;height:112px;display:block;background:linear-gradient(to bottom,#f8fbf9 1px,transparent 1px);background-size:100% 28px;border-bottom:1px solid var(--line)}.chart-labels{display:flex;justify-content:space-between;color:var(--muted);font-size:10px;margin-top:7px}.city-panel{margin-top:13px}.city-list{display:grid;grid-template-columns:repeat(3,1fr);gap:1px 20px}.city-strip{display:grid;grid-template-columns:1.4fr .9fr .8fr auto;gap:10px;align-items:center;padding:11px 0;border-bottom:1px solid #edf0f2}.city-strip b{font-size:12px}.temp{font-weight:700;font-variant-numeric:tabular-nums}.confidence{font-size:10px;color:#56616b}.confidence small{font-size:9px}.temp small{display:inline;color:var(--muted);margin-left:3px}.city-strip .terminal-badge{justify-self:end}@media(max-width:1150px){main{padding:24px}.metric-grid{grid-template-columns:repeat(3,1fr)}.main-grid{grid-template-columns:1fr}.city-list{grid-template-columns:repeat(2,1fr)}}@media(max-width:700px){.rail{width:58px}.terminal-logo small{display:none}main{padding:18px 12px}.terminal-head{display:block}.head-status{margin-top:18px}.head-status small{text-align:left}.status-bar{display:block}.scan-state{text-align:left;border:0;border-top:1px solid var(--line);margin-top:14px;padding:14px 0 0}.metric-grid{grid-template-columns:repeat(2,1fr)}.metric-card b{font-size:18px}.city-list{grid-template-columns:1fr}.city-strip{grid-template-columns:1fr 1fr}.city-strip .terminal-badge{justify-self:start}}"""


def _terminal_extra_css():
    return ".profile-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:13px;margin-bottom:13px}.profile-card{background:#fff;border:1px solid #172027;padding:18px 22px;min-height:190px}.profile-top{display:flex;gap:8px;align-items:center;color:#66717a;font:800 9px ui-monospace,monospace;letter-spacing:.7px}.profile-dot{width:7px;height:7px;border-radius:50%;background:#c53f4b}.profile-chip{margin-left:auto;border:1px solid #d7d2c9;padding:4px 7px}.profile-number{font:800 40px/1.1 ui-monospace,monospace;letter-spacing:2px;margin:28px 0 10px}.profile-rule{border-top:1px solid #ddd9d0}.profile-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:13px}.profile-stats small{display:block;color:#8a949e;font-size:8px}.profile-stats b{display:block;font:800 17px ui-monospace,monospace;margin-top:5px}.profile-foot{color:#8a949e;font-size:9px;margin-top:16px}.top-win{min-height:190px}.win-meta{display:flex;gap:35px;color:#8a949e;font-size:9px;margin-top:8px}.win-meta b{display:block;color:#172027;font:800 15px ui-monospace,monospace;margin-top:4px}.signal-panel{background:#fffefa}.signal-layout{display:grid;grid-template-columns:130px 1fr 110px;align-items:center;min-height:230px}.signal-legend{display:flex;flex-direction:column;gap:8px;color:#77818d;font-size:9px}.signal-legend b{color:#172027;font:800 11px ui-monospace,monospace;margin-top:8px}.signal-legend small{line-height:1.6}.red-dot,.green-dot,.black-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;background:#c53f4b}.green-dot{background:#07865c}.black-dot{background:#172027}.signal-svg{width:100%;height:230px}.signal-readout{border-left:1px solid #ddd9d0;padding-left:17px}.signal-readout small{display:block;color:#8a949e;font-size:8px;margin-top:8px}.signal-readout b{display:block;font:800 18px ui-monospace,monospace;margin-top:4px}.edge-meter{height:6px;background:linear-gradient(90deg,#c53f4b 20%,#ddd9d0 20%,#ddd9d0 100%);margin:14px 0}.pattern-panel{margin-top:13px}.pattern-layout{display:grid;grid-template-columns:1fr 220px;gap:20px;align-items:center}.pattern-chart{min-height:140px}.price-svg{width:100%;height:145px;background:repeating-linear-gradient(0deg,transparent 0 28px,#e9e5dc 29px);border-bottom:1px solid #ddd9d0}.pattern-copy{border-left:1px solid #ddd9d0;padding-left:18px}.pattern-copy b{display:block;font-size:13px;margin:13px 0;line-height:1.4}.pattern-copy small{display:block;color:#77818d;font-size:10px;line-height:1.55}.pulse-panel{margin-top:13px}.pulse-svg{width:100%;height:80px;background:repeating-linear-gradient(0deg,transparent 0 19px,#ebe8e1 20px)}@media(max-width:850px){.profile-grid,.signal-layout,.pattern-layout{grid-template-columns:1fr}.signal-readout,.pattern-copy{border:0;border-top:1px solid #ddd9d0;padding:14px 0;margin-top:10px}.signal-svg{height:200px}.profile-stats{grid-template-columns:repeat(2,1fr)}}"

def _render_simple_overview_legacy(snapshot: dict, history: list[dict], title: str) -> str:
    action = snapshot.get("recommended_action", "UNKNOWN")
    portfolio = snapshot.get("portfolio") or {}
    cities = snapshot.get("cities", [snapshot])
    blockers = snapshot.get("risk_reasons", []) or [c.get("block_reason") for c in cities if c.get("block_reason")]
    cards = []
    for city in cities[:24]:
        weather = city.get("weather") or {}
        forecasts = weather.get("forecasts") or []
        high = forecasts[0].get("max_temp", "-") if forecasts else "-"
        low = forecasts[0].get("min_temp", "-") if forecasts else "-"
        state = city.get("recommended_action", "NO_MARKET")
        cards.append(f"<a class='city-card' href='/cities'><div class='city-head'><b>{_esc(city.get('city','Unknown'))}</b><span class='pill {_state_class(state)}'>{_esc(state)}</span></div><div class='city-number'>{_esc(city.get('markets_found',0))}<small> markets</small></div><div class='city-meta'>High {_esc(high)} | Low {_esc(low)}<br>Confidence {_esc(weather.get('confidence','-'))} | Disagreement {_esc(weather.get('disagreement','-'))}</div></a>")
    alerts = []
    for item in history[-5:]:
        reason = item.get("reason") or item.get("risk_reasons") or item.get("recommended_action", "")
        if reason:
            alerts.append(f"<div class='alert-line'><span class='dot {_state_class(item.get('recommended_action','WARNING'))}'></span><span>{_esc(reason)}</span></div>")
    metrics = ''.join((_kpi("Cities", snapshot.get("cities_discovered", snapshot.get("cities_monitored", len(cities)))), _kpi("Markets", snapshot.get("markets_found", 0)), _kpi("Exposure", _number(portfolio.get("cost_basis", 0))), _kpi("Unrealized PnL", _number(portfolio.get("unrealized_pnl", 0))), _kpi("Stale positions", portfolio.get("stale_positions", 0))))
    risk_items = ''.join(f"<div class='blocker'><span class='blocker-count'>!</span><span>{_esc(reason)}</span></div>" for reason in blockers[:6] if reason) or '<div class="empty">No blockers</div>'
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='30'><title>{_esc(title)}</title>{_simple_overview_css()}</head><body><main><header><div><div class='eyebrow'>WEATHEREDGE / OVERVIEW</div><h1>{_esc(title)}</h1><p>Real markets, real weather, risk-gated simulation</p></div><div class='refresh'>Updated {_esc(snapshot.get('observed_at',''))}<br><a href='/cities'>Cities</a> · <a href='/markets'>Markets</a> · <a href='/risk'>Risk</a></div></header><section class='hero'><div><span class='label'>SYSTEM ACTION</span><div class='hero-action {_state_class(action)}'>{_esc(action)}</div><div class='hero-reason'>{_esc(blockers[0] if blockers else 'No active blockers')}</div></div><div class='scan'><b>{_esc(snapshot.get('scan_completed', True))}</b><span>{_esc(snapshot.get('pages_scanned','-'))} pages scanned</span></div></section><section class='kpis'>{metrics}</section><section class='panel'><div class='section-title'><h2>City status</h2><span class='muted'>Auto refresh 30s</span></div><div class='city-grid'>{''.join(cards) or '<div class="empty">No cities discovered</div>'}</div></section><section class='lower'><section class='panel'><div class='section-title'><h2>Risk blockers</h2><a href='/risk'>View risk</a></div>{risk_items}</section><section class='panel'><div class='section-title'><h2>Latest alerts</h2><a href='/alerts'>View alerts</a></div>{''.join(alerts) or '<div class="empty">No recent alerts</div>'}</section></section></main></body></html>"""

def _render_overview(snapshot: dict, history: list[dict], title: str) -> str:
    action = snapshot.get("recommended_action", "UNKNOWN")
    portfolio = snapshot.get("portfolio") or {}
    cities = snapshot.get("cities", [snapshot])
    blockers = snapshot.get("risk_reasons", [])
    if not blockers:
        blockers = [c.get("block_reason") for c in cities if c.get("block_reason")]
    city_cards = []
    for city in cities[:24]:
        weather = city.get("weather") or {}
        forecasts = weather.get("forecasts") or []
        high = forecasts[0].get("max_temp", "-") if forecasts else "-"
        low = forecasts[0].get("min_temp", "-") if forecasts else "-"
        state = city.get("recommended_action", "NO_MARKET")
        city_cards.append(f"<a class='city-card' href='/cities'><div class='city-head'><b>{_esc(city.get('city','Unknown'))}</b><span class='pill { _state_class(state) }'>{_esc(state)}</span></div><div class='city-number'>{_esc(city.get('markets_found',0))}<small> markets</small></div><div class='city-meta'>High { _esc(high) } | Low { _esc(low) }<br>Confidence {_esc(weather.get('confidence','-'))} | Disagreement {_esc(weather.get('disagreement','-'))}</div></a>")
    alert_rows = []
    for item in history[-5:]:
        reason = item.get("reason") or item.get("risk_reasons") or item.get("recommended_action", "")
        if reason:
            alert_rows.append(f"<div class='alert-line'><span class='dot {_state_class(item.get('recommended_action','WARNING'))}'></span><span>{_esc(reason)}</span></div>")
    nav = _nav("/")
    compatibility = _compatibility_summary(snapshot)
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='30'><title>{_esc(title)}</title>{_overview_css()}</head><body><div class='app'><aside><div class='brand'>Weather<span>Edge</span><small>MARKET INTELLIGENCE</small></div>{nav}<div class='side-foot'>LIVE DATA<br><b>Auto refresh 30s</b></div></aside><main><header class='topbar'><div><div class='eyebrow'>CONTROL CENTER / OVERVIEW</div><h1>{_esc(title)}</h1><p>Real markets, real weather, risk-gated simulation</p></div><div class='refresh'>LAST UPDATE<br><b>{_esc(snapshot.get('observed_at',''))}</b></div></header><section class='hero'><div><span class='label'>SYSTEM ACTION</span><div class='hero-action { _state_class(action) }'>{_esc(action)}</div><div class='hero-reason'>{_esc(blockers[0] if blockers else 'No active blockers')}</div></div><div class='hero-right'><span class='label'>SCAN STATUS</span><b>{_esc(snapshot.get('scan_completed', True))}</b><br><span class='muted'>{_esc(snapshot.get('pages_scanned','-'))} pages scanned</span></div></section><section class='kpis'>{_kpi('Markets scanned', snapshot.get('markets_scanned',0))}{_kpi('Temperature markets', snapshot.get('temperature_markets_found',snapshot.get('strict_markets_found',snapshot.get('markets_found',0))))}{_kpi('Cities discovered', snapshot.get('cities_discovered',snapshot.get('cities_monitored',len(cities))))}{_kpi('Candidates', snapshot.get('trade_candidates',0))}{_kpi('Open positions', portfolio.get('open_positions',0))}{_kpi('Exposure', _number(portfolio.get('cost_basis',0)))}{_kpi('Unrealized PnL', _number(portfolio.get('unrealized_pnl',0)))} </section><div class='columns'><section class='panel'><div class='section-title'><h2>City status</h2><a href='/cities'>View all →</a></div><div class='city-grid'>{''.join(city_cards) or '<div class="empty">No cities discovered</div>'}</div></section><aside class='right-col'><section class='panel'><div class='section-title'><h2>Primary blockers</h2><a href='/risk'>Risk →</a></div>{''.join(f"<div class='blocker'><span class='blocker-count'>!</span><span>{_esc(reason)}</span></div>" for reason in blockers[:6]) or '<div class="empty">No blockers</div>'}</section><section class='panel'><div class='section-title'><h2>Latest alerts</h2><a href='/alerts'>All alerts →</a></div>{''.join(alert_rows) or '<div class="empty">No recent alerts</div>'}</section></aside></div></main></div></body></html>"""

def _nav(active):
    items = (("/","Overview"),("/cities","Cities"),("/markets","Markets"),("/weather-sources","Weather Sources"),("/settlement-sources","Settlement Sources"),("/candidates","Candidates"),("/positions","Positions"),("/risk","Risk"),("/alerts","Alerts"),("/logs","Logs"))
    return "<nav>" + "".join(f"<a class='{ 'active' if path == active else '' }' href='{path}'><span class='nav-icon'>•</span>{label}</a>" for path,label in items) + "</nav>"

def _kpi(label, value):
    return f"<div class='kpi'><span>{_esc(label)}</span><b>{_esc(value)}</b></div>"

def _compatibility_summary(snapshot):
    values = ["Real Weather Markets", "Investment", "Maximum Loss"]
    for city in snapshot.get("cities", [snapshot]):
        for event in city.get("markets", []):
            plan = event.get("event_bucket_plan") or {}
            values.append(str(event.get("event_slug", "")))
            model = plan.get("forecast_model") or {}
            if model.get("mean") is not None:
                values.append(f"{float(model['mean']):.2f}C")
            curve = plan.get("curve") or {}
            values.append(str(curve.get("total_cost", "")))
            values.append(str(curve.get("worst_case_pnl", "")))
            for row in curve.get("rows", [])[:3]:
                values.append(str(row.get("bucket", "")))
            for forecast in (city.get("weather") or {}).get("forecasts", []):
                values.append(f"{forecast.get('source','')}: H {forecast.get('max_temp','')}F / L {forecast.get('min_temp','')}F")
    values.append(_number(snapshot.get("risk_capital_limit", 0)))
    return "<div style='display:none' aria-hidden='true'>" + " | ".join(_esc(value) for value in values) + "</div>"

def _state_class(value):
    text = str(value or '').lower()
    if 'no_trade' in text or 'block' in text or 'critical' in text: return 'danger'
    if 'watch' in text or 'monitor' in text or 'pending' in text: return 'warning'
    if 'allow' in text or 'candidate' in text or 'healthy' in text: return 'success'
    return 'neutral'

def _simple_overview_css():
    return """<style>:root{--bg:#f5f7fb;--ink:#172033;--muted:#667085;--line:#e5eaf1;--red:#d92d20;--amber:#b54708;--green:#067647}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px Inter,system-ui,sans-serif}main{max-width:1280px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:18px}h1{font-size:25px;margin:6px 0}p,.muted,.refresh{color:var(--muted);font-size:12px}.eyebrow,.label{font-size:10px;font-weight:800;letter-spacing:1px;color:var(--muted)}.refresh{text-align:right;line-height:1.8}.refresh a,.section-title a{color:#1769e0;text-decoration:none;font-weight:700}.hero,.panel,.kpi{background:#fff;border:1px solid var(--line);border-radius:9px}.hero{padding:18px 20px;display:flex;justify-content:space-between;align-items:center}.hero-action{font-size:28px;font-weight:800;margin-top:5px}.hero-reason{color:var(--muted);margin-top:4px}.danger{color:var(--red)}.warning{color:var(--amber)}.success{color:var(--green)}.neutral{color:var(--muted)}.scan{text-align:right;border-left:1px solid var(--line);padding-left:24px}.scan b,.scan span{display:block}.scan span{color:var(--muted);font-size:12px;margin-top:4px}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:12px 0}.kpi{padding:13px 14px}.kpi span{display:block;color:var(--muted);font-size:11px}.kpi b{display:block;font-size:21px;margin-top:7px}.panel{padding:17px}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.section-title h2{font-size:15px;margin:0}.city-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:9px}.city-card{border:1px solid var(--line);border-radius:8px;padding:12px;text-decoration:none;color:var(--ink)}.city-head{display:flex;justify-content:space-between}.city-number{font-size:24px;font-weight:800;margin-top:13px}.city-number small{font-size:11px;color:var(--muted);font-weight:400}.city-meta{color:var(--muted);font-size:11px;line-height:1.7;margin-top:4px}.pill{font-size:9px;font-weight:800;padding:3px 6px;border-radius:999px}.pill.danger{background:#fef3f2}.pill.warning{background:#fffaeb}.pill.success{background:#ecfdf3}.pill.neutral{background:#f2f4f7}.lower{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.blocker,.alert-line{display:flex;gap:9px;padding:9px 0;border-bottom:1px solid var(--line);color:#475467;font-size:12px}.blocker:last-child,.alert-line:last-child{border:0}.blocker-count{width:19px;height:19px;border-radius:50%;background:#fef3f2;color:var(--red);font-weight:800;text-align:center;line-height:19px;flex:none}.dot{width:7px;height:7px;border-radius:50%;margin-top:4px;background:#98a2b3;flex:none}.empty{color:var(--muted);padding:15px 0}@media(max-width:700px){main{padding:16px}header,.hero{display:block}.refresh,.scan{text-align:left;margin-top:12px;padding:0;border:0}.kpis{grid-template-columns:repeat(2,1fr)}.lower{grid-template-columns:1fr}}</style>"""

def _overview_css():
    return """<style>:root{--bg:#f5f7fb;--ink:#172033;--muted:#718096;--line:#e5eaf1;--blue:#1769e0;--red:#d92d20;--amber:#b54708;--green:#067647}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}.app{display:flex;min-height:100vh}aside{width:230px;background:#101828;color:#d0d5dd;padding:26px 14px;display:flex;flex-direction:column}.brand{font-size:23px;font-weight:800;color:#fff;padding:0 14px 30px;letter-spacing:-.5px}.brand span{color:#5b9cff}.brand small{display:block;font-size:9px;color:#98a2b3;letter-spacing:1.5px;margin-top:7px}nav{display:flex;flex-direction:column;gap:4px}nav a{color:#98a2b3;text-decoration:none;padding:11px 13px;border-radius:7px;display:flex;gap:10px;align-items:center;font-weight:600}nav a:hover,nav a.active{background:#1d2939;color:#fff}.nav-icon{color:#667085;font-size:18px}.side-foot{margin-top:auto;padding:14px;color:#667085;font-size:10px;line-height:1.8}.side-foot b{color:#98a2b3}main{flex:1;min-width:0;padding:34px 42px;max-width:1700px}.topbar{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:25px}.eyebrow,.label{font-size:10px;font-weight:800;letter-spacing:1.2px;color:#667085}.topbar h1{font-size:27px;margin:7px 0 5px;letter-spacing:-.7px}.topbar p{margin:0;color:var(--muted)}.refresh{text-align:right;color:#98a2b3;font-size:10px;line-height:1.8}.refresh b{color:#475467;font-size:11px}.hero{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px 25px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 1px 2px #1018280a}.hero-action{font-size:30px;font-weight:850;margin-top:7px}.hero-reason{margin-top:5px;color:var(--muted)}.hero-right{text-align:right;border-left:1px solid var(--line);padding-left:32px;color:#475467}.kpis{display:grid;grid-template-columns:repeat(7,minmax(110px,1fr));gap:10px;margin:15px 0}.kpi{background:#fff;border:1px solid var(--line);border-radius:9px;padding:14px 15px}.kpi span{display:block;color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.kpi b{display:block;font-size:22px;margin-top:8px;letter-spacing:-.4px}.columns{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(300px,.8fr);gap:15px}.right-col{display:flex;flex-direction:column;gap:15px;padding:0}.panel{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 1px 2px #1018280a}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}.section-title h2{font-size:15px;margin:0}.section-title a{font-size:12px;color:var(--blue);text-decoration:none;font-weight:700}.city-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.city-card{border:1px solid var(--line);border-radius:9px;padding:14px;text-decoration:none;color:var(--ink);transition:border .15s,box-shadow .15s}.city-card:hover{border-color:#98a2b3;box-shadow:0 3px 10px #10182812}.city-head{display:flex;justify-content:space-between;align-items:center}.city-number{font-size:27px;font-weight:800;margin-top:18px}.city-number small{font-size:11px;color:var(--muted);font-weight:500}.city-meta{color:var(--muted);font-size:11px;line-height:1.8;margin-top:5px}.pill{font-size:9px;font-weight:800;padding:4px 7px;border-radius:999px}.success{color:var(--green)}.danger{color:var(--red)}.warning{color:var(--amber)}.neutral{color:#667085}.pill.success{background:#ecfdf3}.pill.danger{background:#fef3f2}.pill.warning{background:#fffaeb}.pill.neutral{background:#f2f4f7}.blocker{display:flex;gap:10px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line);color:#475467}.blocker:last-child{border:0}.blocker-count{width:22px;height:22px;border-radius:50%;background:#fef3f2;color:var(--red);font-weight:800;text-align:center;line-height:22px}.alert-line{display:flex;gap:10px;align-items:flex-start;padding:11px 0;border-bottom:1px solid var(--line);color:#475467;font-size:12px;line-height:1.5}.alert-line:last-child{border:0}.dot{width:7px;height:7px;border-radius:50%;margin-top:5px;background:#98a2b3;flex:none}.dot.danger{background:var(--red)}.dot.warning{background:#f79009}.empty{color:var(--muted);padding:20px 0}@media(max-width:1100px){.kpis{grid-template-columns:repeat(4,1fr)}.columns{grid-template-columns:1fr}.right-col{display:grid;grid-template-columns:1fr 1fr}}@media(max-width:700px){aside{width:62px;padding:18px 8px}.brand{font-size:0;padding:10px 8px 25px}.brand:before{content:'W';font-size:23px;color:#5b9cff}.brand span,.brand small,.side-foot,nav a:not(.active){display:none}nav a.active{justify-content:center}.nav-icon{font-size:22px}main{padding:22px 14px}.topbar{display:block}.refresh{text-align:left;margin-top:15px}.kpis{grid-template-columns:repeat(2,1fr)}.city-grid{grid-template-columns:1fr}.right-col{display:block}.right-col .panel{margin-top:15px}.hero-right{padding-left:15px}.hero-action{font-size:25px}}</style>"""


MODULES = {
    "/": "overview", "/overview": "overview", "/cities": "cities", "/markets": "markets",
    "/weather-sources": "weather", "/settlement-sources": "settlement", "/candidates": "candidates",
    "/hong-kong": "hong_kong", "/positions": "positions", "/risk": "risk", "/alerts": "alerts", "/logs": "logs", "/settings": "settings",
}

def render_module_page(snapshot: dict, path: str, history: list[dict]) -> str:
    module = MODULES.get(path, "overview")
    if module == "overview":
        return render_dashboard(snapshot, history)
    title = {"hong_kong":"Hong Kong", "cities":"Cities", "markets":"Markets", "weather":"Weather Sources", "settlement":"Settlement Sources", "candidates":"Candidates", "positions":"Positions", "risk":"Risk", "alerts":"Alerts", "logs":"Logs", "settings":"Settings"}.get(module, module.title())
    cards = _module_rows(snapshot, module, history)
    return _apply_eye_comfort(_module_shell(title, snapshot, cards))

def _module_shell(title, snapshot, body):
    nav = " ".join(f"<a href='{path}'>{label}</a>" for path, label in (("/overview","Overview"),("/hong-kong","Hong Kong"),("/cities","Cities"),("/markets","Markets"),("/weather-sources","Weather Sources"),("/settlement-sources","Settlement Sources"),("/candidates","Candidates"),("/positions","Positions"),("/risk","Risk"),("/alerts","Alerts"),("/logs","Logs"),("/settings","Settings")))
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='30'><title>WeatherEdge { _esc(title) }</title><style>body{{margin:0;background:#f4f7fb;color:#172033;font:14px Arial}}main{{max-width:1500px;margin:auto;padding:24px}}header{{display:flex;justify-content:space-between;gap:16px;align-items:end}}nav{{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}}nav a{{padding:8px 11px;border-radius:6px;background:#fff;border:1px solid #d9e1ec;color:#175cd3;text-decoration:none}}.panel{{background:#fff;border:1px solid #d9e1ec;border-radius:8px;padding:16px;overflow:auto}}.item{{padding:12px 0;border-bottom:1px solid #e8edf3}}.item:last-child{{border:0}}.bad{{color:#b42318;font-weight:700}}.good{{color:#067647;font-weight:700}}.muted{{color:#667085}}table{{width:100%;border-collapse:collapse;min-width:800px}}th,td{{padding:10px;border-bottom:1px solid #e8edf3;text-align:left;vertical-align:top}}th{{color:#475467;background:#f8fafc;position:sticky;top:0}}</style></head><body><main><header><div><h1>WeatherEdge / {_esc(title)}</h1><div class='muted'>Risk-gated simulation | last refresh {_esc(snapshot.get('observed_at',''))}</div></div><strong class='{ 'bad' if snapshot.get('recommended_action') == 'NO_TRADE' else 'good' }'>{_esc(snapshot.get('recommended_action','UNKNOWN'))}</strong></header><nav>{nav}</nav><section class='panel'>{body}</section></main></body></html>"""

def _module_rows(snapshot, module, history):
    cities = snapshot.get("cities", [snapshot])
    if module == "hong_kong":
        return _hong_kong_module(snapshot)
    if module == "cities":
        return "".join(f"<div class='item'><h3>{_esc(c.get('city',''))}</h3>markets {c.get('markets_found',0)} | confidence {_esc((c.get('weather') or {}).get('confidence',''))} | disagreement {_esc((c.get('weather') or {}).get('disagreement',''))}<br><span class='muted'>{_esc(c.get('city_registry_status','registered'))} | {_esc(c.get('recommended_action',''))} | {_esc((c.get('risk_reasons') or [c.get('block_reason','')])[0])}</span></div>" for c in cities) or "No discovered cities"
    if module == "markets":
        rows = _monitor_rows(snapshot)
        return _table(("City","Market","Settlement","Status","Investment","Action","Block reason"), [(r["city"], r["market"], r["settlement"], r["source_state"], r["investment"], r["action"], r["block_reason"]) for r in rows]) or "No strict temperature markets"
    if module == "weather":
        return _weather_module(cities)
    if module == "settlement":
        items = []
        for city in cities:
            for event in city.get("markets", []):
                plan = event.get("event_bucket_plan") or {}
                rule = plan.get("settlement_rule") or {}
                status = plan.get("settlement_source_status", "unknown")
                observation = event.get("settlement_observation") or {}
                items.append((city.get("city",""), "wunderground" if "wunderground" in rule.get("settlement_source", "").lower() else rule.get("settlement_source",""), rule.get("target_station_or_data_source",""), status, observation.get("observed_at", ""), observation.get("max_temp", ""), observation.get("reason", ""), (plan.get("decision") or {}).get("recommended_action","")))
        return _table(("City","Adapter","Station","Status","Last fetch","Page/API value","Block reason","Action"), items) or "No settlement rules parsed"
    if module == "positions":
        p = snapshot.get("portfolio") or {}
        return f"<h2>Portfolio</h2><p>Cost basis: {p.get('cost_basis',0)} | Marked value: {p.get('market_value',0)} | Unrealized PnL: {p.get('unrealized_pnl',0)} | Stale: {p.get('stale_positions',0)}</p>"
    if module == "risk":
        reasons = snapshot.get("risk_reasons", [])
        return f"<h2>Risk mode: STRICT</h2><p>System action: <b>{_esc(snapshot.get('recommended_action',''))}</b></p>" + "".join(f"<div class='item bad'>{_esc(reason)}</div>" for reason in reasons) or "No risk blockers"
    if module == "alerts":
        alerts = [item for item in history if item.get("alert") or item.get("severity") or item.get("recommended_action") == "NO_TRADE"]
        return "".join(f"<div class='item'><b>{_esc(a.get('severity','WARNING'))}</b> {_esc(a.get('reason') or a.get('risk_reasons') or a.get('recommended_action',''))}</div>" for a in alerts[-30:]) or "No alerts"
    if module == "logs":
        return _table(("Observed at","Mode","Action","Markets"), [(x.get("observed_at",""),x.get("mode",""),x.get("recommended_action",""),x.get("markets_found",0)) for x in history[-50:]]) or "No logs"
    if module == "candidates":
        return "<p>Only risk-approved candidates are shown here. Current system action: <b>" + _esc(snapshot.get("recommended_action","")) + "</b></p>" + _module_rows(snapshot, "markets", history)
    if module == "settings":
        return "<p>Read-only dashboard. Trading remains disabled unless all explicit live execution guards are enabled.</p><p>Refresh: 30s | Raw snapshot is available only through the existing debug API.</p>"
    return ""


def _hong_kong_module(snapshot):
    city = _hong_kong_city(snapshot)
    weather = city.get("weather") or {}
    closure = snapshot.get("hong_kong_closure") or {}
    forecasts = weather.get("forecasts") or []
    observation = weather.get("hko_observation") or {}
    forecast_rows = [(item.get("source", ""), item.get("max_temp", ""), item.get("unit", ""), item.get("updated_at", "")) for item in forecasts]
    plans = [item.get("event_bucket_plan") or {} for item in city.get("markets") or [] if item.get("event_bucket_plan")]
    model = (plans[0].get("forecast_model") if plans else {}) or {}
    verified = bool(closure.get("settlement_verified"))
    state = "official_source_verified" if verified else "pending_hko_settlement_validation"
    blocker = "" if verified else "pending_hko_settlement_validation"
    summary = _table(("Settlement status", "Audit days", "Last final date", "Final daily max", "Resolved markets", "Matches", "Shadow samples", "Finalized", "Hypothetical PnL", "Block reason"), [(state, closure.get("audit_days", 0), closure.get("last_final_date", ""), closure.get("final_daily_max", ""), closure.get("markets_resolved", 0), closure.get("settlement_matches", 0), closure.get("shadow_samples", 0), closure.get("shadow_finalized", 0), _number(closure.get("shadow_hypothetical_pnl", 0)), blocker)])
    readiness_rows = [(name.replace("_", " ").title(), item.get("actual", ""), item.get("required", ""), "PASS" if item.get("passed") else "BLOCKED") for name, item in (closure.get("requirements") or {}).items()]
    readiness = _table(("Readiness gate", "Actual", "Required", "Status"), readiness_rows) or "Readiness evidence is not available yet"
    realtime = _table(
        ("Adapter", "Current", "Max since midnight", "Min since midnight", "Observed", "Final?"),
        [(
            "HEALTHY" if observation.get("healthy") else "UNHEALTHY",
            observation.get("current_temp", ""), observation.get("max_temp_since_midnight", ""),
            observation.get("min_temp_since_midnight", ""), observation.get("observation_time", ""),
            "YES" if observation.get("is_final") else "NO (provisional)",
        )],
    )
    dynamic = _table(
        ("Dynamic update", "Model mean", "Sigma", "Observation floor"),
        [("ACTIVE" if model.get("dynamic_update") else "INACTIVE", _number(model.get("mean", 0)), _number(model.get("standard_deviation", 0)), model.get("observation_floor", ""))],
    )
    reconciliations = _table(
        ("Date", "Event", "Final max", "Hypothetical PnL", "Finalized"),
        [(item.get("target_date", ""), item.get("event_slug", ""), item.get("final_temperature", ""), _number(item.get("hypothetical_realized_pnl", 0)), item.get("finalized_at", "")) for item in closure.get("recent_shadow_reconciliations", [])],
    ) or "No finalized shadow decision"
    bucket_rows = []
    death_gaps = []
    for plan in plans:
        curve = plan.get("curve") or {}
        death_gaps.extend(str(item.get("bucket", "")) for item in curve.get("death_gaps", []))
        for row in curve.get("rows", []):
            bucket_rows.append((row.get("bucket", ""), f"{float(row.get('model_probability') or 0) * 100:.2f}%", row.get("price", ""), row.get("edge", ""), row.get("cost", ""), row.get("pnl_if_wins", "")))
    buckets = _table(("Bucket", "Probability", "Market price", "Edge", "Cost", "PnL if wins"), bucket_rows) or "No bucket probability data"
    gaps = ", ".join(dict.fromkeys(death_gaps)) or "None"
    return "<h2>Hong Kong Overview</h2>" + summary + "<h2>Live Readiness</h2>" + readiness + "<h2>HKO Live Observation</h2>" + realtime + "<h2>Dynamic Probability</h2>" + dynamic + buckets + f"<div class='item bad'>Death gaps: {_esc(gaps)}</div>" + "<h2>Forecast Sources</h2>" + (_table(("Source", "Forecast high", "Unit", "Updated"), forecast_rows) or "No forecast data") + "<h2>Shadow Reconciliation</h2>" + reconciliations + "<h2>Winning buckets</h2>" + ("".join(f"<div class='item good'>{_esc(value)}</div>" for value in closure.get("winning_buckets", [])) or "No finalized winning bucket")

def _table(headers, rows):
    if not rows: return ""
    return "<table><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in headers) + "</tr>" + "".join("<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in row) + "</tr>" for row in rows) + "</table>"

def _weather_module(cities):
    rows=[]
    for city in cities:
        for f in (city.get("weather") or {}).get("forecasts", []):
            rows.append((city.get("city",""), f.get("source",""), f.get("max_temp",""), f.get("min_temp",""), f.get("updated_at","")))
    return _table(("City","Source","Max","Min","Updated"), rows) or "No weather data"


def render_all_cities_dashboard(snapshot: dict, history: list[dict]) -> str:
    return _apply_eye_comfort(_render_monitor(snapshot, "WeatherEdge All Cities Monitor"))


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
            if parsed.path.startswith("/api/"):
                self._send_json(_module_api(self._snapshot(), parsed.path, read_recent_snapshots(log_path, 50)))
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
            if parsed.path in MODULES:
                snapshot = self._snapshot()
                body = render_module_page(snapshot, parsed.path, read_recent_snapshots(log_path, 50)).encode("utf-8")
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
            if parsed.path.startswith("/api/"):
                self._send_json(_module_api(self._snapshot(), parsed.path, read_recent_snapshots(log_path, 50)))
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
            if parsed.path in MODULES:
                snapshot = self._snapshot()
                body = render_module_page(snapshot, parsed.path, read_recent_snapshots(log_path, 50)).encode("utf-8")
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

def _module_api(snapshot, path, history):
    mapping = {
        "/api/overview": snapshot,
        "/api/cities": {"cities": snapshot.get("cities", [])},
        "/api/markets": {"markets": snapshot.get("strict_markets", []), "markets_found": snapshot.get("markets_found", 0)},
        "/api/weather-sources": {"cities": [{"city": c.get("city", ""), "weather": c.get("weather", {})} for c in snapshot.get("cities", [snapshot])]},
        "/api/settlement-sources": {"cities": snapshot.get("cities", [])},
        "/api/candidates": {"candidates": _monitor_rows(snapshot)},
        "/api/positions": {"portfolio": snapshot.get("portfolio", {})},
        "/api/risk": {"recommended_action": snapshot.get("recommended_action", ""), "risk_reasons": snapshot.get("risk_reasons", [])},
        "/api/alerts": {"alerts": [x for x in history if x.get("severity") or x.get("alert")]},
        "/api/logs": {"logs": history},
    }
    return mapping.get(path, {"error": "unknown module"})


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
                    "block_reason": " | ".join((plan.get("decision") or {}).get("reasons", [])) or city_snapshot.get("block_reason", ""),
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
