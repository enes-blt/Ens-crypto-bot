import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import run
from .data import fetch_funding_rates, fetch_klines, load_csv, load_funding_csv, save_csv, save_funding_csv
from .research import candidate_configs_v2, candidate_configs_v3, portfolio_walk_forward, walk_forward
from .paper import daemon as paper_daemon, prepare as prepare_paper, run_once as paper_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto trend research CLI (no live trading)")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download")
    download.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT"], required=True)
    download.add_argument("--days", type=int, default=365 * 3)
    funding_command = sub.add_parser("download-funding")
    funding_command.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT"], required=True)
    funding_command.add_argument("--days", type=int, default=365 * 3)
    backtest = sub.add_parser("backtest")
    backtest.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT"], required=True)
    research = sub.add_parser("research")
    research.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT"], required=True)
    research_v2 = sub.add_parser("research-v2")
    research_v2.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT"], required=True)
    sub.add_parser("portfolio-v2")
    research_v3 = sub.add_parser("research-v3")
    research_v3.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT"], required=True)
    sub.add_parser("portfolio-v3")
    sub.add_parser("prepare-paper")
    paper_once_parser = sub.add_parser("paper-once")
    paper_once_parser.add_argument("--no-refresh", action="store_true")
    paper_daemon_parser = sub.add_parser("paper-daemon")
    paper_daemon_parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()

    root = Path.cwd()
    if args.command == "prepare-paper":
        print(json.dumps(prepare_paper(root), indent=2))
        return
    if args.command == "paper-once":
        print(json.dumps(paper_once(root, refresh_data=not args.no_refresh), indent=2))
        return
    if args.command == "paper-daemon":
        paper_daemon(root, args.interval_seconds)
        return
    if args.command in {"portfolio-v2", "portfolio-v3"}:
        datasets = {}
        components = {}
        for symbol in ("BTCUSDT", "ETHUSDT"):
            datasets[symbol] = (
                load_csv(root / "data" / f"{symbol}_1h.csv"),
                load_funding_csv(root / "data" / f"{symbol}_funding.csv"),
            )
            version = "v3" if args.command == "portfolio-v3" else "v2"
            component_path = root / "reports" / f"{symbol}_research-{version}.json"
            if component_path.exists():
                components[symbol] = json.loads(component_path.read_text(encoding="utf-8"))
        result = portfolio_walk_forward(
            datasets,
            components if len(components) == 2 else None,
            candidates=candidate_configs_v3() if args.command == "portfolio-v3" else candidate_configs_v2(),
            correlation_threshold=0.75 if args.command == "portfolio-v3" else None,
            correlated_exposure=0.70 if args.command == "portfolio-v3" else 1.0,
        )
        reports = root / "reports"
        reports.mkdir(exist_ok=True)
        report_path = reports / ("PORTFOLIO_v3.json" if args.command == "portfolio-v3" else "PORTFOLIO_v2.json")
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "folds"}, indent=2))
        print(f"Rapor: {report_path}")
        return
    data_path = root / "data" / f"{args.symbol}_1h.csv"
    if args.command in {"download", "download-funding"}:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        candles = []
        if args.command == "download":
            candles = fetch_klines(args.symbol, "1h", int(start.timestamp() * 1000), int(end.timestamp() * 1000))
            save_csv(candles, data_path)
        funding = fetch_funding_rates(args.symbol, int(start.timestamp() * 1000), int(end.timestamp() * 1000))
        funding_path = root / "data" / f"{args.symbol}_funding.csv"
        save_funding_csv(funding, funding_path)
        print(f"{len(candles)} mum ve {len(funding)} funding kaydi kaydedildi")
        return
    funding_path = root / "data" / f"{args.symbol}_funding.csv"
    candles = load_csv(data_path)
    funding = load_funding_csv(funding_path)
    if args.command == "research":
        result = walk_forward(candles, funding)
    elif args.command == "research-v2":
        result = walk_forward(candles, funding, candidates=candidate_configs_v2())
    elif args.command == "research-v3":
        result = walk_forward(candles, funding, candidates=candidate_configs_v3())
    else:
        result = run(candles, funding_rates=funding)
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    report_path = reports / f"{args.symbol}_{args.command}.json"
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k not in {"trade_log", "config", "folds", "monthly_returns_pct"}}
    print(json.dumps(summary, indent=2))
    print(f"Rapor: {report_path}")


if __name__ == "__main__":
    main()
