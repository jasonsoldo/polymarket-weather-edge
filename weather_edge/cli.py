import argparse
import json
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

    markets_parser = sub.add_parser("live-markets")
    markets_parser.add_argument("--city", default="")
    markets_parser.add_argument("--limit", type=int, default=100)
    markets_parser.add_argument("--tag-id", default="")
    markets_parser.add_argument("--slug", default="")
    markets_parser.add_argument("--query", default="")
    markets_parser.add_argument("--pages", type=int, default=3)
    markets_parser.add_argument("--include-broad-weather", action="store_true")

    sub.add_parser("live-tags")

    weather_parser = sub.add_parser("live-weather")
    weather_parser.add_argument("--city", required=True)
    weather_parser.add_argument("--lat", type=float, required=True)
    weather_parser.add_argument("--lon", type=float, required=True)
    weather_parser.add_argument("--date", required=True)

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

    monitor_all_parser = sub.add_parser("live-monitor-all")
    monitor_all_parser.add_argument("--date", required=True)
    monitor_all_parser.add_argument("--output", default="logs/live_monitor_all.jsonl")
    monitor_all_parser.add_argument("--interval", type=int, default=300)
    monitor_all_parser.add_argument("--limit", type=int, default=100)
    monitor_all_parser.add_argument("--books", action="store_true")
    monitor_all_parser.add_argument("--pages", type=int, default=3)
    monitor_all_parser.add_argument("--include-broad-weather", action="store_true")
    monitor_all_parser.add_argument("--max-runs", type=int)
    monitor_all_parser.add_argument("--history-db", default="data/market_history.sqlite")

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
    dry_run_parser.add_argument("--include-broad-weather", action="store_true")

    args = parser.parse_args(argv)

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

    if args.command == "live-markets":
        from .market_scanner import fetch_weather_markets

        markets = [
            market.to_dict()
            for market in fetch_weather_markets(
                args.limit,
                city=args.city,
                tag_id=args.tag_id,
                slug=args.slug,
                query=args.query,
                pages=args.pages,
                include_broad_weather=args.include_broad_weather,
            )
        ]
        payload = {"markets_found": len(markets), "markets": markets}
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

        weather = fetch_weather_snapshot(args.city, args.lat, args.lon, args.date)
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
            include_broad_weather=args.include_broad_weather,
            max_runs=args.max_runs,
            history_db=args.history_db,
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
            include_broad_weather=args.include_broad_weather,
            max_runs=args.max_runs,
            history_db=args.history_db,
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
        print(json.dumps(result, indent=2))
        return 0

    return 1


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
