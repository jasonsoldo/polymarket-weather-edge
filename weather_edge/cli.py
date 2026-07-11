import argparse
import json
import time
from datetime import date, timedelta
from dataclasses import asdict

from .backtest import run_backtest
from .config import load_risk_config
from .io import curve_to_dict, load_plan
from .live_pipeline import run_live_dry_run
from .monitor import build_live_snapshot, run_all_cities_monitor_loop, run_live_monitor_loop
from .pnl_curve import build_pnl_curve
from .risk_manager import RiskConfig, evaluate_trade_plan
from .simulator import simulate_settlement
from .storage import init_db, save_analysis
from .strategy_config import load_strategy_config
from .settlement_sources.wunderground_browser import fetch_wunderground_browser


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="weather-edge")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init-db")
    init_parser.add_argument("--db", default="data/weather_edge.sqlite")

    analyze_parser = sub.add_parser("analyze")
    analyze_parser.add_argument("--plan", required=True)
    analyze_parser.add_argument("--config")
    analyze_parser.add_argument("--db")

    simulate_parser = sub.add_parser("simulate")
    simulate_parser.add_argument("--plan", required=True)
    simulate_parser.add_argument("--winning-bucket", required=True)
    simulate_parser.add_argument("--config")
    simulate_parser.add_argument("--db")

    backtest_parser = sub.add_parser("backtest")
    backtest_parser.add_argument("--file", required=True)
    backtest_parser.add_argument("--config")

    validation_parser = sub.add_parser("validate-history")
    validation_parser.add_argument("--file", required=True)
    validation_parser.add_argument("--min-days", type=int, default=30)
    validation_parser.add_argument("--min-exact-match-rate", type=float, default=0.90)
    validation_parser.add_argument("--max-missing-rate", type=float, default=0.10)
    validation_parser.add_argument("--min-bucket-match-rate", type=float, default=0.90)

    backfill_parser = sub.add_parser("settlement-backfill")
    backfill_parser.add_argument("--input", required=True)
    backfill_parser.add_argument("--resolutions", required=True)
    backfill_parser.add_argument("--output", required=True)

    markets_parser = sub.add_parser("live-markets")
    markets_parser.add_argument("--city", default="")
    markets_parser.add_argument("--limit", type=int, default=100)
    markets_parser.add_argument("--tag-id", default="")
    markets_parser.add_argument("--slug", default="")
    markets_parser.add_argument("--query", default="")
    markets_parser.add_argument("--pages", type=int, default=3)
    markets_parser.add_argument("--max-pages", type=int, default=20)
    markets_parser.add_argument("--scan-all-pages", action="store_true")
    markets_parser.add_argument("--include-broad-weather", action="store_true")

    sub.add_parser("live-tags")

    weather_parser = sub.add_parser("live-weather")
    weather_parser.add_argument("--city", required=True)
    weather_parser.add_argument("--lat", type=float, required=True)
    weather_parser.add_argument("--lon", type=float, required=True)
    weather_parser.add_argument("--date", required=True)

    wu_parser = sub.add_parser("wunderground-fetch")
    wu_parser.add_argument("--station", required=True)
    wu_parser.add_argument("--date", required=True)
    wu_parser.add_argument("--unit", choices=("C", "F"), default="C")
    wu_parser.add_argument("--url", required=True)
    wu_parser.add_argument("--artifact-dir", default="data/wunderground_artifacts")
    wu_parser.add_argument("--timeout-ms", type=int, default=30000)
    wu_parser.add_argument("--retries", type=int, default=2)

    wu_collect = sub.add_parser("wunderground-collect")
    wu_collect.add_argument("--station", required=True)
    wu_collect.add_argument("--start-date", required=True)
    wu_collect.add_argument("--end-date", required=True)
    wu_collect.add_argument("--unit", choices=("C", "F"), default="C")
    wu_collect.add_argument("--url-template", required=True)
    wu_collect.add_argument("--artifact-dir", default="data/wunderground_artifacts")
    wu_collect.add_argument("--output", default="data/wunderground_samples.jsonl")
    wu_collect.add_argument("--interval", type=float, default=15.0)
    wu_collect.add_argument("--timeout-ms", type=int, default=30000)

    wu_discovered = sub.add_parser("wunderground-collect-discovered")
    wu_discovered.add_argument("--markets-file", required=True)
    wu_discovered.add_argument("--unit", choices=("C", "F"), default="C")
    wu_discovered.add_argument("--output", default="data/wunderground_discovered.jsonl")
    wu_discovered.add_argument("--artifact-dir", default="data/wunderground_artifacts")
    wu_discovered.add_argument("--interval", type=float, default=15.0)

    monitor_parser = sub.add_parser("live-monitor")
    monitor_parser.add_argument("--city", required=True)
    monitor_parser.add_argument("--lat", type=float, required=True)
    monitor_parser.add_argument("--lon", type=float, required=True)
    monitor_parser.add_argument("--date", required=True)
    monitor_parser.add_argument("--limit", type=int, default=100)
    monitor_parser.add_argument("--books", action="store_true")
    monitor_parser.add_argument("--tag-id", default="")
    monitor_parser.add_argument("--slug", default="")
    monitor_parser.add_argument("--query", default="")
    monitor_parser.add_argument("--pages", type=int, default=3)
    monitor_parser.add_argument("--max-pages", type=int, default=20)
    monitor_parser.add_argument("--scan-all-pages", action="store_true")
    monitor_parser.add_argument("--include-broad-weather", action="store_true")

    monitor_loop_parser = sub.add_parser("live-monitor-loop")
    monitor_loop_parser.add_argument("--city", required=True)
    monitor_loop_parser.add_argument("--lat", type=float, required=True)
    monitor_loop_parser.add_argument("--lon", type=float, required=True)
    monitor_loop_parser.add_argument("--date", required=True)
    monitor_loop_parser.add_argument("--output", default="logs/live_monitor.jsonl")
    monitor_loop_parser.add_argument("--interval", type=int, default=300)
    monitor_loop_parser.add_argument("--limit", type=int, default=100)
    monitor_loop_parser.add_argument("--books", action="store_true")
    monitor_loop_parser.add_argument("--tag-id", default="")
    monitor_loop_parser.add_argument("--slug", default="")
    monitor_loop_parser.add_argument("--query", default="")
    monitor_loop_parser.add_argument("--pages", type=int, default=3)
    monitor_loop_parser.add_argument("--include-broad-weather", action="store_true")
    monitor_loop_parser.add_argument("--max-runs", type=int)
    monitor_loop_parser.add_argument("--history-db", default="data/market_history.sqlite")
    monitor_loop_parser.add_argument("--alerts-log", default="logs/alerts.jsonl")

    monitor_all_parser = sub.add_parser("live-monitor-all")
    monitor_all_parser.add_argument("--date", required=True)
    monitor_all_parser.add_argument("--output", default="logs/live_monitor_all.jsonl")
    monitor_all_parser.add_argument("--interval", type=int, default=300)
    monitor_all_parser.add_argument("--limit", type=int, default=100)
    monitor_all_parser.add_argument("--books", action="store_true")
    monitor_all_parser.add_argument("--pages", type=int, default=3)
    monitor_all_parser.add_argument("--max-pages", type=int, default=20)
    monitor_all_parser.add_argument("--scan-all-pages", action="store_true")
    monitor_all_parser.add_argument("--include-broad-weather", action="store_true")
    monitor_all_parser.add_argument("--max-runs", type=int)
    monitor_all_parser.add_argument("--history-db", default="data/market_history.sqlite")
    monitor_all_parser.add_argument("--alerts-log", default="logs/alerts.jsonl")

    web_monitor_parser = sub.add_parser("web-monitor")
    web_monitor_parser.add_argument("--host", default="127.0.0.1")
    web_monitor_parser.add_argument("--port", type=int, default=8080)
    web_monitor_parser.add_argument("--city", required=True)
    web_monitor_parser.add_argument("--lat", type=float, required=True)
    web_monitor_parser.add_argument("--lon", type=float, required=True)
    web_monitor_parser.add_argument("--date", required=True)
    web_monitor_parser.add_argument("--log", default="logs/live_monitor.jsonl")
    web_monitor_parser.add_argument("--limit", type=int, default=100)
    web_monitor_parser.add_argument("--pages", type=int, default=3)
    web_monitor_parser.add_argument("--include-broad-weather", action="store_true")

    web_monitor_all_parser = sub.add_parser("web-monitor-all")
    web_monitor_all_parser.add_argument("--host", default="127.0.0.1")
    web_monitor_all_parser.add_argument("--port", type=int, default=8080)
    web_monitor_all_parser.add_argument("--date", required=True)
    web_monitor_all_parser.add_argument("--log", default="logs/live_monitor_all.jsonl")
    web_monitor_all_parser.add_argument("--limit", type=int, default=100)
    web_monitor_all_parser.add_argument("--pages", type=int, default=3)
    web_monitor_all_parser.add_argument("--include-broad-weather", action="store_true")

    dry_run_parser = sub.add_parser("live-dry-run")
    dry_run_parser.add_argument("--city", required=True)
    dry_run_parser.add_argument("--lat", type=float, required=True)
    dry_run_parser.add_argument("--lon", type=float, required=True)
    dry_run_parser.add_argument("--date", required=True)
    dry_run_parser.add_argument("--strategy-config")
    dry_run_parser.add_argument("--risk-config")
    dry_run_parser.add_argument("--orders-db", default="data/orders.sqlite")
    dry_run_parser.add_argument("--positions-db", default="data/positions.sqlite")
    dry_run_parser.add_argument("--limit", type=int, default=20)
    dry_run_parser.add_argument("--tag-id", default="")
    dry_run_parser.add_argument("--slug", default="")
    dry_run_parser.add_argument("--query", default="")
    dry_run_parser.add_argument("--pages", type=int, default=2)
    dry_run_parser.add_argument("--max-pages", type=int, default=20)
    dry_run_parser.add_argument("--scan-all-pages", action="store_true")
    dry_run_parser.add_argument("--include-broad-weather", action="store_true")
    dry_run_parser.add_argument("--full", action="store_true", help="print the complete raw simulation payload")

    portfolio_parser = sub.add_parser("portfolio")
    portfolio_parser.add_argument("--positions-db", default="data/positions.sqlite")

    exit_parser = sub.add_parser("exit-dry-run")
    exit_parser.add_argument("--positions-db", default="data/positions.sqlite")
    exit_parser.add_argument("--orders-db", default="data/orders.sqlite")
    exit_parser.add_argument("--reason", default="manual_protective_exit")

    reconcile_parser = sub.add_parser("reconcile-orders")
    reconcile_parser.add_argument("--orders-db", default="data/orders.sqlite")
    reconcile_parser.add_argument("--positions-db", default="data/positions.sqlite")

    args = parser.parse_args(argv)

    if args.command == "wunderground-fetch":
        result = fetch_wunderground_browser(args.url, args.station, args.date, args.unit, args.artifact_dir, args.timeout_ms, args.retries)
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.status in {"wu_browser_supported", "wu_verified"} else 2

    if args.command == "wunderground-collect":
        from pathlib import Path
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        if end < start:
            parser.error("--end-date must not be earlier than --start-date")
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        current = start
        collected = failed = 0
        with output.open("a", encoding="utf-8") as handle:
            while current <= end:
                target = current.isoformat()
                url = args.url_template.replace("{station}", args.station).replace("{date}", target)
                result = fetch_wunderground_browser(url, args.station, target, args.unit, args.artifact_dir, args.timeout_ms, 2)
                row = result.to_dict()
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                if result.status in {"wu_unavailable", "wu_source_mismatch"}:
                    failed += 1
                    print(json.dumps({"date": target, "status": result.status, "reason": result.reason}))
                    if "403" in result.reason or "429" in result.reason or "CAPTCHA" in result.reason:
                        break
                else:
                    collected += 1
                    print(json.dumps({"date": target, "status": result.status, "daily_high": result.daily_high, "daily_low": result.daily_low}))
                current += timedelta(days=1)
                if current <= end:
                    time.sleep(max(0.0, args.interval))
        print(json.dumps({"output": str(output), "collected": collected, "failed": failed}, indent=2))
        return 0 if failed == 0 else 2

    if args.command == "wunderground-collect-discovered":
        from .wunderground_collector import collect_discovered_markets
        rows = collect_discovered_markets(args.markets_file, args.output, args.artifact_dir, args.unit, args.interval)
        print(json.dumps({"markets_collected": len(rows), "output": args.output, "statuses": {status: sum(row["status"] == status for row in rows) for status in sorted({row["status"] for row in rows})}}, indent=2))
        return 0

    if args.command == "init-db":
        init_db(args.db)
        print(json.dumps({"db": args.db, "initialized": True}, indent=2))
        return 0

    config = load_risk_config(args.config) if getattr(args, "config", None) else RiskConfig()

    if args.command == "analyze":
        state, buckets = load_plan(args.plan)
        curve = build_pnl_curve(buckets, config.max_uncovered_probability)
        decision = evaluate_trade_plan(curve, state, config)
        payload = _analysis_payload(curve, decision)
        if args.db:
            save_analysis(args.db, state.market_id, "analyze", payload["curve"], payload["decision"])
        print(json.dumps(payload, indent=2))
        return 0 if decision.allowed else 2

    if args.command == "simulate":
        state, buckets = load_plan(args.plan)
        curve = build_pnl_curve(buckets, config.max_uncovered_probability)
        decision = evaluate_trade_plan(curve, state, config)
        simulation = simulate_settlement(curve, decision, args.winning_bucket)
        payload = _analysis_payload(curve, decision)
        payload["simulation"] = asdict(simulation)
        if args.db:
            save_analysis(args.db, state.market_id, "simulate", payload["curve"], payload["decision"])
        print(json.dumps(payload, indent=2))
        return 0 if simulation.filled else 2

    if args.command == "backtest":
        summary, results = run_backtest(args.file, config)
        print(json.dumps({"summary": asdict(summary), "results": results}, indent=2))
        return 0

    if args.command == "validate-history":
        from .historical_validation import load_jsonl, validate_history

        result = validate_history(load_jsonl(args.file), args.min_days, args.min_exact_match_rate, args.max_missing_rate, args.min_bucket_match_rate)
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.verified else 2

    if args.command == "settlement-backfill":
        from .settlement_backfill import backfill_resolutions, read_jsonl, write_jsonl

        rows = backfill_resolutions(read_jsonl(args.input), read_jsonl(args.resolutions))
        write_jsonl(args.output, rows)
        print(json.dumps({"input": args.input, "resolutions": args.resolutions, "output": args.output, "rows": len(rows), "backfilled": sum(bool(row.get("resolution_backfilled")) for row in rows)}, indent=2))
        return 0

    if args.command == "live-markets":
        from .market_scanner import fetch_weather_markets, get_last_scan_stats

        markets = [
            market.to_dict()
            for market in fetch_weather_markets(
                args.limit,
                city=args.city,
                tag_id=args.tag_id,
                slug=args.slug,
                query=args.query,
                pages=args.pages,
                max_pages=args.max_pages,
                scan_all_pages=args.scan_all_pages,
                include_broad_weather=args.include_broad_weather,
            )
        ]
        payload = {"markets_found": len(markets), "markets": markets, **get_last_scan_stats()}
        if not markets and args.city and not args.include_broad_weather:
            payload["reason"] = "no strict city temperature markets found"
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "live-tags":
        from .market_scanner import discover_weather_tags

        tags = [tag.to_dict() for tag in discover_weather_tags()]
        print(json.dumps({"weather_tags_found": len(tags), "tags": tags}, indent=2))
        return 0

    if args.command == "live-weather":
        from .weather_sources import fetch_weather_snapshot
        from .monitor import _city_unit

        weather = fetch_weather_snapshot(args.city, args.lat, args.lon, args.date, unit=_city_unit(args.city))
        print(json.dumps(weather.to_dict(), indent=2))
        return 0

    if args.command == "live-monitor":
        snapshot = build_live_snapshot(
            args.city,
            args.lat,
            args.lon,
            args.date,
            market_limit=args.limit,
            include_books=args.books,
            tag_id=args.tag_id,
            slug=args.slug,
            query=args.query,
            pages=args.pages,
            max_pages=args.max_pages,
            scan_all_pages=args.scan_all_pages,
            include_broad_weather=args.include_broad_weather,
        )
        print(json.dumps(snapshot, indent=2))
        return 0

    if args.command == "live-monitor-loop":
        runs = run_live_monitor_loop(
            args.city,
            args.lat,
            args.lon,
            args.date,
            args.output,
            interval_seconds=args.interval,
            market_limit=args.limit,
            include_books=args.books,
            tag_id=args.tag_id,
            slug=args.slug,
            query=args.query,
            pages=args.pages,
            max_pages=args.max_pages,
            scan_all_pages=args.scan_all_pages,
            include_broad_weather=args.include_broad_weather,
            max_runs=args.max_runs,
            history_db=args.history_db,
            alerts_log=args.alerts_log,
        )
        print(json.dumps({"output": args.output, "runs": runs}, indent=2))
        return 0

    if args.command == "live-monitor-all":
        runs = run_all_cities_monitor_loop(
            args.date,
            args.output,
            interval_seconds=args.interval,
            market_limit=args.limit,
            include_books=args.books,
            pages=args.pages,
            max_pages=args.max_pages,
            scan_all_pages=args.scan_all_pages,
            include_broad_weather=args.include_broad_weather,
            max_runs=args.max_runs,
            history_db=args.history_db,
            alerts_log=args.alerts_log,
        )
        print(json.dumps({"output": args.output, "runs": runs}, indent=2))
        return 0

    if args.command == "web-monitor":
        from .web_monitor import run_web_monitor

        run_web_monitor(
            args.host,
            args.port,
            args.city,
            args.lat,
            args.lon,
            args.date,
            log_path=args.log,
            market_limit=args.limit,
            pages=args.pages,
            include_broad_weather=args.include_broad_weather,
        )
        return 0

    if args.command == "web-monitor-all":
        from .web_monitor import run_all_cities_web_monitor

        run_all_cities_web_monitor(
            args.host,
            args.port,
            args.date,
            log_path=args.log,
            market_limit=args.limit,
            pages=args.pages,
            include_broad_weather=args.include_broad_weather,
        )
        return 0

    if args.command == "live-dry-run":
        strategy = load_strategy_config(args.strategy_config)
        risk_config = load_risk_config(args.risk_config) if args.risk_config else RiskConfig()
        result = run_live_dry_run(
            args.city,
            args.lat,
            args.lon,
            args.date,
            strategy,
            risk_config,
            args.orders_db,
            args.positions_db,
            market_limit=args.limit,
            tag_id=args.tag_id,
            slug=args.slug,
            query=args.query,
            pages=args.pages,
            include_broad_weather=args.include_broad_weather,
        )
        print(json.dumps(result if args.full else _dry_run_summary(result), indent=2))
        return 0

    if args.command == "portfolio":
        from .portfolio import portfolio_snapshot

        print(json.dumps(portfolio_snapshot(args.positions_db), indent=2))
        return 0

    if args.command == "exit-dry-run":
        from .exit_manager import build_protective_exit_plan
        from .orderbook import fetch_book_summary
        from .position_manager import load_positions
        from .trade_executor import execute_trade_plan

        positions = load_positions(args.positions_db)
        books = {position.token_id: fetch_book_summary(position.token_id) for position in positions}
        plan = build_protective_exit_plan(positions, books, args.reason)
        executions = execute_trade_plan(plan, StrategyConfig(), args.orders_db, args.positions_db)
        print(json.dumps({"plan": plan.to_dict(), "executions": [item.to_dict() for item in executions]}, indent=2))
        return 0

    if args.command == "reconcile-orders":
        from .reconciliation import reconcile_live_orders

        print(json.dumps({"orders": reconcile_live_orders(args.orders_db, args.positions_db)}, indent=2))
        return 0

    return 1


def _dry_run_summary(payload: dict) -> dict:
    weather = payload.get("weather") or {}
    forecasts = [
        {
            "source": forecast.get("source"),
            "high": forecast.get("max_temp"),
            "low": forecast.get("min_temp"),
            "unit": forecast.get("unit"),
        }
        for forecast in weather.get("forecasts", [])
    ]
    events = []
    for result in payload.get("results", []):
        plan = result.get("event_bucket_plan") or {}
        curve = plan.get("curve") or {}
        decision = plan.get("decision") or {}
        candidate = plan.get("simulation_candidate") or {}
        candidate_curve = candidate.get("curve") or {}
        events.append({
            "event": result.get("event_slug"),
            "settlement": plan.get("settlement_source_status"),
            "action": decision.get("recommended_action"),
            "reasons": decision.get("reasons", []),
            "orders": [
                {"bucket": order.get("bucket"), "price": order.get("price"), "edge": order.get("edge")}
                for order in plan.get("orders", [])
            ],
            "cost": curve.get("total_cost", 0),
            "worst_pnl": curve.get("worst_case_pnl", 0),
            "best_pnl": curve.get("best_case_pnl", 0),
            "death_gaps": [gap.get("bucket") for gap in curve.get("death_gaps", [])],
            "simulation_candidate": {
                "action": candidate.get("recommended_action"),
                "cost": candidate_curve.get("total_cost", 0),
                "worst_pnl": candidate_curve.get("worst_case_pnl", 0),
                "best_pnl": candidate_curve.get("best_case_pnl", 0),
                "death_gaps": [gap.get("bucket") for gap in candidate_curve.get("death_gaps", [])],
                "reasons": candidate.get("not_executable_reasons", []),
            } if candidate else None,
        })
    event_reasons = []
    event_blocked = False
    for event in events:
        if event.get("action") == "block_new_position":
            event_blocked = True
        for reason in event.get("reasons", []):
            if reason not in event_reasons:
                event_reasons.append(reason)
    if event_blocked:
        recommended_action = "NO_TRADE"
        blocked_by = payload.get("blocked_by") or "event_risk"
        risk_reasons = ["NO_TRADE", *event_reasons]
    else:
        recommended_action = payload.get("recommended_action") or ("WATCH" if events else "NO_TRADE")
        blocked_by = payload.get("blocked_by")
        risk_reasons = payload.get("risk_reasons", [])
    return {
        "mode": payload.get("mode"),
        "city": payload.get("city"),
        "target_date": payload.get("target_date"),
        "weather": {
            "forecasts": forecasts,
            "disagreement": weather.get("disagreement"),
            "confidence": weather.get("confidence"),
        },
        "markets_found": payload.get("markets_found", 0),
        "events": events,
        "recommended_action": recommended_action,
        "blocked_by": blocked_by,
        "risk_reasons": risk_reasons,
        "safety": payload.get("safety", []),
    }

def _analysis_payload(curve, decision) -> dict:
    return {
        "curve": curve_to_dict(curve),
        "decision": {
            "allowed": decision.allowed,
            "recommended_action": decision.recommended_action,
            "reasons": list(decision.reasons),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
