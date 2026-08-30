import json
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import Config, run
from .data import (
    fetch_funding_rates,
    fetch_klines,
    load_csv,
    load_funding_csv,
    save_csv,
    save_funding_csv,
)
from .research import candidate_configs_v2


HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def prepare(root: Path) -> dict:
    """Select and freeze one v2 config per symbol using only known history."""
    selections = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        refresh(root, symbol)
        candles = load_csv(root / "data" / f"{symbol}_1h.csv")
        funding = load_funding_csv(root / "data" / f"{symbol}_funding.csv")
        training_end = candles[-1].open_time_ms
        training_start = training_end - 730 * DAY_MS
        sample = [c for c in candles if c.open_time_ms >= training_start - 40 * DAY_MS]
        sample_funding = [r for r in funding if r.funding_time_ms >= sample[0].open_time_ms]
        ranked = []
        for config in candidate_configs_v2():
            result = run(sample, config, sample_funding, trade_start_ms=training_start)
            ranked.append((_selection_score(result), config, result))
        ranked.sort(key=lambda row: row[0], reverse=True)
        score, config, result = ranked[0]
        selections[symbol] = {
            "config": asdict(config),
            "selection_score": round(score, 4),
            "training_start_ms": training_start,
            "training_end_ms": training_end,
            "training_summary": _summary(result),
        }
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    paper_start_ms = ((now_ms // 14_400_000) + 1) * 14_400_000
    payload = {
        "mode": "paper_only",
        "created_at_ms": now_ms,
        "paper_start_ms": paper_start_ms,
        "symbols": selections,
    }
    paper_dir = root / "paper"
    paper_dir.mkdir(exist_ok=True)
    (paper_dir / "config.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _init_db(paper_dir / "paper.db")
    return payload


def refresh(root: Path, symbol: str) -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    candle_path = root / "data" / f"{symbol}_1h.csv"
    existing = load_csv(candle_path) if candle_path.exists() else []
    start_ms = max(existing[-1].open_time_ms - 2 * HOUR_MS, now_ms - 800 * DAY_MS) if existing else now_ms - 800 * DAY_MS
    downloaded = fetch_klines(symbol, "1h", start_ms, now_ms)
    merged = {c.open_time_ms: c for c in existing}
    merged.update({c.open_time_ms: c for c in downloaded})
    save_csv([merged[t] for t in sorted(merged)], candle_path)

    funding_path = root / "data" / f"{symbol}_funding.csv"
    existing_funding = load_funding_csv(funding_path)
    funding_start = max(existing_funding[-1].funding_time_ms - DAY_MS, now_ms - 800 * DAY_MS) if existing_funding else now_ms - 800 * DAY_MS
    downloaded_funding = fetch_funding_rates(symbol, funding_start, now_ms)
    merged_funding = {r.funding_time_ms: r for r in existing_funding}
    merged_funding.update({r.funding_time_ms: r for r in downloaded_funding})
    save_funding_csv([merged_funding[t] for t in sorted(merged_funding)], funding_path)


def run_once(root: Path, refresh_data: bool = True) -> dict:
    config_path = root / "paper" / "config.json"
    if not config_path.exists():
        raise FileNotFoundError("Once `crypto-trend prepare-paper` calistirin.")
    paper_config = json.loads(config_path.read_text(encoding="utf-8"))
    if paper_config.get("mode") != "paper_only":
        raise ValueError("Guvenlik hatasi: yalnizca paper_only modu desteklenir.")
    start_ms = int(paper_config["paper_start_ms"])
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    statuses = {}
    db_path = root / "paper" / "paper.db"
    _init_db(db_path)
    for symbol, selection in paper_config["symbols"].items():
        if refresh_data:
            refresh(root, symbol)
        candles = load_csv(root / "data" / f"{symbol}_1h.csv")
        # Keep the current forming hour as the execution bar at 4h boundaries;
        # older bars are complete and signals use only completed 4h buckets.
        candles = [c for c in candles if start_ms - 40 * DAY_MS <= c.open_time_ms <= (now_ms // HOUR_MS) * HOUR_MS]
        funding = [r for r in load_funding_csv(root / "data" / f"{symbol}_funding.csv") if r.funding_time_ms >= candles[0].open_time_ms]
        result = run(candles, Config(**selection["config"]), funding, trade_start_ms=start_ms, close_at_end=False)
        statuses[symbol] = _paper_summary(result)
        _store_run(db_path, now_ms, symbol, result)
    output = {"mode": "paper_only", "run_at_ms": now_ms, "paper_start_ms": start_ms, "symbols": statuses}
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "paper_status.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def daemon(root: Path, interval_seconds: int = 300) -> None:
    while True:
        try:
            result = run_once(root, refresh_data=True)
            print(json.dumps(result), flush=True)
        except Exception as exc:
            print(json.dumps({"mode": "paper_only", "error": str(exc)}), flush=True)
        time.sleep(max(interval_seconds, 60))


def _selection_score(result: dict) -> float:
    if result["trades"] < 20 or result["max_drawdown_pct"] > 30:
        return -10_000 + result["net_return_pct"]
    return result["sharpe_365"] + 0.02 * result["net_return_pct"] - 0.03 * result["max_drawdown_pct"]


def _summary(result: dict) -> dict:
    keys = ["net_return_pct", "max_drawdown_pct", "trades", "profit_factor", "sharpe_365", "total_fees_usdt", "total_funding_usdt"]
    return {key: result[key] for key in keys}


def _paper_summary(result: dict) -> dict:
    keys = ["final_equity", "net_return_pct", "max_drawdown_pct", "trades", "open_position_at_end", "position_state", "total_fees_usdt", "total_funding_usdt"]
    defaults = {"total_fees_usdt": 0.0, "total_funding_usdt": 0.0}
    return {key: result.get(key, defaults.get(key)) for key in keys}


def _init_db(path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_at_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                equity REAL NOT NULL,
                position_json TEXT,
                PRIMARY KEY (run_at_ms, symbol)
            );
            CREATE TABLE IF NOT EXISTS trades (
                symbol TEXT NOT NULL,
                entry_time_ms INTEGER NOT NULL,
                exit_time_ms INTEGER NOT NULL,
                trade_json TEXT NOT NULL,
                PRIMARY KEY (symbol, entry_time_ms)
            );
        """)


def _store_run(path: Path, run_at_ms: int, symbol: str, result: dict) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?)",
            (run_at_ms, symbol, result["final_equity"], json.dumps(result["position_state"])),
        )
        for trade in result["trade_log"]:
            connection.execute(
                "INSERT OR REPLACE INTO trades VALUES (?, ?, ?, ?)",
                (symbol, trade["entry_time_ms"], trade["exit_time_ms"], json.dumps(trade)),
            )
