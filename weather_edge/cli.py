import argparse
import json
from dataclasses import asdict

from .backtest import run_backtest
from .config import load_risk_config
from .io import curve_to_dict, load_plan
from .pnl_curve import build_pnl_curve
from .risk_manager import RiskConfig, evaluate_trade_plan
from .simulator import simulate_settlement
from .storage import init_db, save_analysis


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
