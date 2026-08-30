import csv
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Candle, FundingRate


BASE_URL = "https://fapi.binance.com/fapi/v1/klines"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
    """Download public candles, paging without API credentials."""
    symbol = symbol.upper()
    candles: list[Candle] = []
    cursor = start_ms
    while cursor < end_ms:
        query = urlencode({
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1500,
        })
        request = Request(f"{BASE_URL}?{query}", headers={"User-Agent": "crypto-trend-bot/0.1"})
        with urlopen(request, timeout=30) as response:
            rows = json.load(response)
        if not rows:
            break
        batch = [
            Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in rows
        ]
        candles.extend(batch)
        next_cursor = batch[-1].open_time_ms + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.1)
    unique = {c.open_time_ms: c for c in candles if c.open_time_ms < end_ms}
    return [unique[t] for t in sorted(unique)]


def save_csv(candles: list[Candle], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["open_time_ms", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow([c.open_time_ms, c.open, c.high, c.low, c.close, c.volume])


def load_csv(path: Path) -> list[Candle]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return [
            Candle(
                int(r["open_time_ms"]), float(r["open"]), float(r["high"]),
                float(r["low"]), float(r["close"]), float(r["volume"]),
            )
            for r in rows
        ]


def fetch_funding_rates(symbol: str, start_ms: int, end_ms: int) -> list[FundingRate]:
    rates: list[FundingRate] = []
    cursor = start_ms
    while cursor < end_ms:
        query = urlencode({"symbol": symbol.upper(), "startTime": cursor, "endTime": end_ms, "limit": 1000})
        request = Request(f"{FUNDING_URL}?{query}", headers={"User-Agent": "crypto-trend-bot/0.1"})
        with urlopen(request, timeout=30) as response:
            rows = json.load(response)
        if not rows:
            break
        batch = [FundingRate(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]
        rates.extend(batch)
        next_cursor = batch[-1].funding_time_ms + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.1)
    unique = {r.funding_time_ms: r for r in rates if r.funding_time_ms < end_ms}
    return [unique[t] for t in sorted(unique)]


def save_funding_csv(rates: list[FundingRate], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["funding_time_ms", "rate"])
        for rate in rates:
            writer.writerow([rate.funding_time_ms, rate.rate])


def load_funding_csv(path: Path) -> list[FundingRate]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [FundingRate(int(r["funding_time_ms"]), float(r["rate"])) for r in csv.DictReader(handle)]
