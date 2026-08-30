from dataclasses import asdict
from datetime import datetime, timezone
from itertools import product
from statistics import mean, pstdev

from .backtest import Config, run
from .models import Candle, FundingRate


def candidate_configs() -> list[Config]:
    candidates: list[Config] = []
    for strategy, adx_min, stop, trail in product(
        ["trend_breakout", "trend_pullback", "volatility_breakout"],
        [15.0, 20.0, 25.0],
        [1.5, 2.0],
        [2.5, 3.5],
    ):
        for donchian in ([20, 55] if strategy == "trend_breakout" else [20]):
            candidates.append(Config(strategy=strategy, adx_min=adx_min, stop_atr=stop, trailing_atr=trail, donchian_period=donchian))
    return candidates


def candidate_configs_v2() -> list[Config]:
    """Long/cash candidates with slower 4h entries to reduce turnover."""
    candidates: list[Config] = []
    for strategy, adx_min, stop, trail in product(
        ["trend_breakout", "trend_pullback"],
        [15.0, 20.0, 25.0],
        [1.5, 2.0],
        [3.0, 4.0],
    ):
        periods = [20, 55, 100] if strategy == "trend_breakout" else [20]
        for donchian in periods:
            candidates.append(Config(
                strategy=strategy, entry_timeframe="4h", allow_short=False,
                adx_min=adx_min, stop_atr=stop, trailing_atr=trail,
                donchian_period=donchian,
            ))
    return candidates


def candidate_configs_v3() -> list[Config]:
    """Daily regime and volatility-targeted long/cash candidates."""
    candidates: list[Config] = []
    for strategy, adx_min, trail, regime, target_vol in product(
        ["trend_breakout", "trend_pullback"],
        [15.0, 20.0],
        [3.0, 4.0],
        ["daily_ema200", "daily_ema100_slope"],
        [0.025, 0.04],
    ):
        periods = [20, 55] if strategy == "trend_breakout" else [20]
        for donchian in periods:
            candidates.append(Config(
                strategy=strategy, entry_timeframe="4h", allow_short=False,
                regime_filter=regime, target_daily_vol=target_vol,
                adx_min=adx_min, stop_atr=2.0, trailing_atr=trail,
                donchian_period=donchian,
            ))
    return candidates


def walk_forward(candles: list[Candle], funding: list[FundingRate], train_days: int = 730, test_days: int = 180, candidates: list[Config] | None = None, first_test_ms: int | None = None) -> dict:
    day_ms = 86_400_000
    first = candles[0].open_time_ms
    last = candles[-1].open_time_ms
    fold_start = first_test_ms or first + train_days * day_ms
    folds = []
    candidates = candidates or candidate_configs()
    warmup_days = 240 if any(c.regime_filter != "none" for c in candidates) else 40
    while fold_start + test_days * day_ms <= last:
        train_start = fold_start - train_days * day_ms
        test_end = fold_start + test_days * day_ms
        train_slice = [c for c in candles if train_start - warmup_days * day_ms <= c.open_time_ms < fold_start]
        train_funding = [r for r in funding if train_slice[0].open_time_ms <= r.funding_time_ms < fold_start]
        ranked = []
        for config in candidates:
            result = run(train_slice, config, train_funding, trade_start_ms=train_start)
            score = _score(result)
            ranked.append((score, config, result))
        ranked.sort(key=lambda item: item[0], reverse=True)
        _, selected, train_result = ranked[0]
        test_slice = [c for c in candles if fold_start - warmup_days * day_ms <= c.open_time_ms < test_end]
        test_funding = [r for r in funding if test_slice[0].open_time_ms <= r.funding_time_ms < test_end]
        test_result = run(test_slice, selected, test_funding, trade_start_ms=fold_start)
        folds.append({
            "train_start": _date(train_start), "test_start": _date(fold_start), "test_end": _date(test_end),
            "selected": asdict(selected),
            "train": _summary(train_result), "test": _summary(test_result),
        })
        fold_start = test_end
    compounded = 1.0
    for fold in folds:
        compounded *= 1 + fold["test"]["net_return_pct"] / 100
    return {
        "method": "rolling 730-day train / 180-day unseen test",
        "candidate_count": len(candidates),
        "folds": folds,
        "combined_unseen_return_pct": round((compounded - 1) * 100, 2),
        "profitable_test_folds": sum(f["test"]["net_return_pct"] > 0 for f in folds),
        "test_fold_count": len(folds),
    }


def portfolio_walk_forward(
    datasets: dict[str, tuple[list[Candle], list[FundingRate]]],
    component_results: dict[str, dict] | None = None,
    candidates: list[Config] | None = None,
    correlation_threshold: float | None = None,
    correlated_exposure: float = 1.0,
) -> dict:
    """Combine independently selected sleeves using inverse training volatility."""
    day_ms = 86_400_000
    first_test = max(candles[0].open_time_ms for candles, _ in datasets.values()) + 730 * day_ms
    aligned = component_results and len({tuple(f["test_start"] for f in result["folds"]) for result in component_results.values()}) == 1
    selected_candidates = candidates or candidate_configs_v2()
    component = component_results if aligned else {
        symbol: walk_forward(candles, funding, candidates=selected_candidates, first_test_ms=first_test)
        for symbol, (candles, funding) in datasets.items()
    }
    symbols = sorted(component)
    fold_count = min(len(component[s]["folds"]) for s in symbols)
    folds = []
    compounded = 1.0
    for index in range(fold_count):
        component_folds = {s: component[s]["folds"][index] for s in symbols}
        test_start = component_folds[symbols[0]]["test_start"]
        train_start_ms = _timestamp(component_folds[symbols[0]]["train_start"])
        test_start_ms = _timestamp(test_start)
        inverse_vol = {}
        for symbol in symbols:
            candles = datasets[symbol][0]
            inverse_vol[symbol] = 1 / max(_daily_volatility(candles, train_start_ms, test_start_ms), 1e-9)
        total = sum(inverse_vol.values())
        weights = {s: inverse_vol[s] / total for s in symbols}
        correlation = _daily_correlation(datasets[symbols[0]][0], datasets[symbols[1]][0], train_start_ms, test_start_ms)
        exposure = correlated_exposure if correlation_threshold is not None and correlation >= correlation_threshold else 1.0
        combined_return = exposure * sum(weights[s] * component_folds[s]["test"]["net_return_pct"] for s in symbols)
        compounded *= 1 + combined_return / 100
        folds.append({
            "test_start": test_start,
            "test_end": component_folds[symbols[0]]["test_end"],
            "weights": {s: round(weights[s] * exposure, 4) for s in symbols},
            "cash_weight": round(1 - exposure, 4),
            "training_correlation": round(correlation, 4),
            "component_returns_pct": {s: component_folds[s]["test"]["net_return_pct"] for s in symbols},
            "combined_return_pct": round(combined_return, 2),
            "selected": {s: component_folds[s]["selected"] for s in symbols},
        })
    return {
        "method": "independent 730-day selection / inverse-volatility weighted 180-day unseen sleeves",
        "candidate_count_per_symbol": len(selected_candidates),
        "folds": folds,
        "combined_unseen_return_pct": round((compounded - 1) * 100, 2),
        "profitable_test_folds": sum(f["combined_return_pct"] > 0 for f in folds),
        "test_fold_count": len(folds),
        "components": {s: {k: v for k, v in component[s].items() if k != "folds"} for s in symbols},
    }


def _score(result: dict) -> float:
    if result["trades"] < 20 or result["max_drawdown_pct"] > 30:
        return -10_000 + result["net_return_pct"]
    return result["sharpe_365"] + 0.02 * result["net_return_pct"] - 0.03 * result["max_drawdown_pct"]


def _summary(result: dict) -> dict:
    keys = ["net_return_pct", "cagr_pct", "max_drawdown_pct", "trades", "win_rate_pct", "profit_factor", "sharpe_365", "sortino_365", "total_fees_usdt", "total_funding_usdt", "benchmark_buy_hold_pct"]
    return {key: result[key] for key in keys}


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()


def _timestamp(date_text: str) -> int:
    return int(datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _daily_volatility(candles: list[Candle], start_ms: int, end_ms: int) -> float:
    daily: dict[str, float] = {}
    for candle in candles:
        if start_ms <= candle.open_time_ms < end_ms:
            daily[_date(candle.open_time_ms)] = candle.close
    closes = list(daily.values())
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    return pstdev(returns) if len(returns) > 1 else 0.0


def _daily_correlation(first: list[Candle], second: list[Candle], start_ms: int, end_ms: int) -> float:
    def returns_by_day(candles: list[Candle]) -> dict[str, float]:
        closes: dict[str, float] = {}
        for candle in candles:
            if start_ms <= candle.open_time_ms < end_ms:
                closes[_date(candle.open_time_ms)] = candle.close
        days = sorted(closes)
        return {days[i]: closes[days[i]] / closes[days[i - 1]] - 1 for i in range(1, len(days))}
    a, b = returns_by_day(first), returns_by_day(second)
    common = sorted(set(a) & set(b))
    if len(common) < 2:
        return 0.0
    x, y = [a[d] for d in common], [b[d] for d in common]
    mx, my = mean(x), mean(y)
    numerator = sum((u - mx) * (v - my) for u, v in zip(x, y))
    denominator = (sum((u - mx) ** 2 for u in x) * sum((v - my) ** 2 for v in y)) ** 0.5
    return numerator / denominator if denominator else 0.0
