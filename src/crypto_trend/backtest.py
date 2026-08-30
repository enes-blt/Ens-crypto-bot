from dataclasses import asdict, dataclass
from math import isnan
from statistics import pstdev

from .indicators import adx, atr, donchian_previous, ema
from .metrics import performance_metrics
from .models import Candle, FundingRate, Trade


@dataclass(frozen=True)
class Config:
    strategy: str = "trend_breakout"
    entry_timeframe: str = "1h"
    allow_short: bool = True
    regime_filter: str = "none"
    target_daily_vol: float | None = None
    initial_equity: float = 10_000.0
    risk_fraction: float = 0.005
    max_leverage: float = 2.0
    fee_rate: float = 0.0005
    slippage_rate: float = 0.0002
    donchian_period: int = 20
    adx_period: int = 14
    adx_min: float = 20.0
    atr_period: int = 14
    stop_atr: float = 2.0
    trailing_atr: float = 3.0


def resample_4h(candles: list[Candle]) -> tuple[list[Candle], list[int]]:
    return _resample(candles, 14_400_000)


def resample_1d(candles: list[Candle]) -> tuple[list[Candle], list[int]]:
    return _resample(candles, 86_400_000)


def _resample(candles: list[Candle], bucket_ms: int) -> tuple[list[Candle], list[int]]:
    bars: list[Candle] = []
    mapping: list[int] = []
    bucket: list[Candle] = []
    current_key = None
    for candle in candles:
        key = candle.open_time_ms // bucket_ms
        if current_key is not None and key != current_key:
            bars.append(_aggregate(bucket))
            bucket = []
        current_key = key
        bucket.append(candle)
        mapping.append(len(bars))
    if bucket:
        bars.append(_aggregate(bucket))
    return bars, mapping


def run(
    candles: list[Candle],
    config: Config = Config(),
    funding_rates: list[FundingRate] | None = None,
    trade_start_ms: int | None = None,
    close_at_end: bool = True,
) -> dict:
    if len(candles) < 850:
        raise ValueError("En az 850 adet 1 saatlik mum gerekir (4s EMA200 isinma periyodu).")
    high = [c.high for c in candles]
    low = [c.low for c in candles]
    close = [c.close for c in candles]
    atr14 = atr(high, low, close, config.atr_period)
    adx14 = adx(high, low, close, config.adx_period)
    ema20_1h = ema(close, 20)
    upper, lower = donchian_previous(high, low, config.donchian_period)
    four_h, mapping = resample_4h(candles)
    four_high = [c.high for c in four_h]
    four_low = [c.low for c in four_h]
    four_close = [c.close for c in four_h]
    ema50, ema200 = ema(four_close, 50), ema(four_close, 200)
    atr14_4h = atr(four_high, four_low, four_close, config.atr_period)
    adx14_4h = adx(four_high, four_low, four_close, config.adx_period)
    ema20_4h = ema(four_close, 20)
    upper_4h, lower_4h = donchian_previous(four_high, four_low, config.donchian_period)
    daily, daily_mapping = resample_1d(candles)
    daily_close = [c.close for c in daily]
    daily_ema100, daily_ema200 = ema(daily_close, 100), ema(daily_close, 200)
    daily_vol30 = _rolling_volatility(daily_close, 30)

    equity = config.initial_equity
    peak = equity
    max_drawdown = 0.0
    trades: list[Trade] = []
    position = None
    curve: list[tuple[int, float]] = [(candles[0].open_time_ms, equity)]
    funding_by_hour = {r.funding_time_ms: r.rate for r in (funding_rates or [])}

    for i in range(1, len(candles)):
        c = candles[i]
        previous = i - 1
        new_four_hour_bar = mapping[i] != mapping[previous]
        new_day = daily_mapping[i] != daily_mapping[previous]
        daily_index = daily_mapping[previous] if new_day else daily_mapping[previous] - 1
        # At a new 4h boundary the previous bucket has just completed. Inside
        # a bucket, use the bucket before it to avoid reading an unfinished bar.
        four_index = mapping[previous] if new_four_hour_bar else mapping[previous] - 1
        if config.entry_timeframe == "4h":
            signal_index = four_index
            signal_close, signal_atr, signal_adx = four_close, atr14_4h, adx14_4h
            signal_ema20, signal_upper, signal_lower = ema20_4h, upper_4h, lower_4h
            trailing_update = new_four_hour_bar
        elif config.entry_timeframe == "1h":
            signal_index = previous
            signal_close, signal_atr, signal_adx = close, atr14, adx14
            signal_ema20, signal_upper, signal_lower = ema20_1h, upper, lower
            trailing_update = True
        else:
            raise ValueError(f"Bilinmeyen giris zaman dilimi: {config.entry_timeframe}")
        if position:
            rate = funding_by_hour.get(c.open_time_ms, 0.0)
            funding_payment = c.open * position["quantity"] * rate * (1 if position["side"] == "long" else -1)
            equity -= funding_payment
            position["funding"] += funding_payment
            # Trailing level uses only the previous completed candle, so the
            # current candle cannot move its own stop retroactively.
            if trailing_update and signal_index >= 0 and not isnan(signal_atr[signal_index]):
                candidate = signal_close[signal_index] - config.trailing_atr * signal_atr[signal_index] if position["side"] == "long" else signal_close[signal_index] + config.trailing_atr * signal_atr[signal_index]
                position["stop"] = max(position["stop"], candidate) if position["side"] == "long" else min(position["stop"], candidate)
            stop_hit = c.low <= position["stop"] if position["side"] == "long" else c.high >= position["stop"]
            if stop_hit:
                raw_exit = position["stop"]
                exit_price = _slip(raw_exit, position["side"], config.slippage_rate, entry=False)
                fee = exit_price * position["quantity"] * config.fee_rate
                gross = ((exit_price - position["entry"]) if position["side"] == "long" else (position["entry"] - exit_price)) * position["quantity"]
                pnl = gross - position["entry_fee"] - fee
                equity += gross - fee
                pnl -= position["funding"]
                trades.append(Trade(position["side"], position["time"], c.open_time_ms, position["entry"], exit_price, position["quantity"], pnl, position["entry_fee"] + fee, position["funding"], "atr_stop"))
                position = None
        indicator_invalid = signal_index < 1 or signal_index >= len(signal_atr) or isnan(signal_adx[signal_index]) or isnan(signal_atr[signal_index])
        if position or four_index < 199 or indicator_invalid:
            marked = _marked_equity(equity, position, c.close, config.fee_rate)
            curve.append((c.open_time_ms, marked))
            peak = max(peak, marked)
            max_drawdown = max(max_drawdown, (peak - marked) / peak)
            continue
        if trade_start_ms is not None and c.open_time_ms < trade_start_ms:
            curve.append((c.open_time_ms, equity))
            continue
        if config.entry_timeframe == "4h" and not new_four_hour_bar:
            curve.append((c.open_time_ms, equity))
            continue
        trend_long = ema50[four_index] > ema200[four_index]
        trend_short = ema50[four_index] < ema200[four_index]
        if config.regime_filter == "none":
            regime_long = True
        elif daily_index < 199:
            regime_long = False
        elif config.regime_filter == "daily_ema200":
            regime_long = daily_close[daily_index] > daily_ema200[daily_index]
        elif config.regime_filter == "daily_ema100_slope":
            regime_long = daily_index >= 119 and daily_close[daily_index] > daily_ema100[daily_index] and daily_ema100[daily_index] > daily_ema100[daily_index - 20]
        else:
            raise ValueError(f"Bilinmeyen rejim filtresi: {config.regime_filter}")
        if config.strategy == "trend_breakout":
            long_signal = trend_long and signal_close[signal_index] > signal_upper[signal_index] and signal_adx[signal_index] >= config.adx_min
            short_signal = trend_short and signal_close[signal_index] < signal_lower[signal_index] and signal_adx[signal_index] >= config.adx_min
        elif config.strategy == "trend_pullback":
            long_signal = trend_long and signal_close[signal_index - 1] <= signal_ema20[signal_index - 1] and signal_close[signal_index] > signal_ema20[signal_index] and signal_adx[signal_index] >= config.adx_min
            short_signal = trend_short and signal_close[signal_index - 1] >= signal_ema20[signal_index - 1] and signal_close[signal_index] < signal_ema20[signal_index] and signal_adx[signal_index] >= config.adx_min
        elif config.strategy == "volatility_breakout":
            long_signal = trend_long and signal_close[signal_index] > signal_close[signal_index - 1] + 0.75 * signal_atr[signal_index] and signal_adx[signal_index] >= config.adx_min
            short_signal = trend_short and signal_close[signal_index] < signal_close[signal_index - 1] - 0.75 * signal_atr[signal_index] and signal_adx[signal_index] >= config.adx_min
        else:
            raise ValueError(f"Bilinmeyen strateji: {config.strategy}")
        long_signal = long_signal and regime_long
        short_signal = short_signal and config.allow_short
        if not (long_signal or short_signal):
            curve.append((c.open_time_ms, equity))
            continue
        side = "long" if long_signal else "short"
        entry = _slip(c.open, side, config.slippage_rate, entry=True)
        stop_distance = config.stop_atr * signal_atr[signal_index]
        risk_multiplier = 1.0
        if config.target_daily_vol is not None and daily_index >= 0 and not isnan(daily_vol30[daily_index]) and daily_vol30[daily_index] > 0:
            risk_multiplier = min(1.0, max(0.25, config.target_daily_vol / daily_vol30[daily_index]))
        risk_qty = equity * config.risk_fraction * risk_multiplier / stop_distance
        leverage_qty = equity * config.max_leverage / entry
        quantity = min(risk_qty, leverage_qty)
        entry_fee = entry * quantity * config.fee_rate
        equity -= entry_fee
        position = {
            "side": side, "entry": entry, "quantity": quantity, "entry_fee": entry_fee,
            "stop": entry - stop_distance if side == "long" else entry + stop_distance,
            "time": c.open_time_ms, "funding": 0.0,
        }
        curve.append((c.open_time_ms, _marked_equity(equity, position, c.close, config.fee_rate)))

    # Mark the final open position to market so reports are comparable and do
    # not silently omit unrealised profit/loss.
    if position and close_at_end:
        last = candles[-1]
        exit_price = _slip(last.close, position["side"], config.slippage_rate, entry=False)
        fee = exit_price * position["quantity"] * config.fee_rate
        gross = ((exit_price - position["entry"]) if position["side"] == "long" else (position["entry"] - exit_price)) * position["quantity"]
        pnl = gross - position["entry_fee"] - fee
        equity += gross - fee
        pnl -= position["funding"]
        trades.append(Trade(position["side"], position["time"], last.open_time_ms, position["entry"], exit_price, position["quantity"], pnl, position["entry_fee"] + fee, position["funding"], "end_of_data"))
        position = None
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    final_equity = _marked_equity(equity, position, candles[-1].close, config.fee_rate)
    curve.append((candles[-1].open_time_ms, final_equity))

    wins = sum(t.pnl > 0 for t in trades)
    gross_profit = sum(max(t.pnl, 0) for t in trades)
    gross_loss = -sum(min(t.pnl, 0) for t in trades)
    result = {
        "initial_equity": config.initial_equity,
        "final_equity": round(final_equity, 2),
        "net_return_pct": round((final_equity / config.initial_equity - 1) * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "trades": len(trades),
        "win_rate_pct": round(100 * wins / len(trades), 2) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "open_position_at_end": position is not None,
        "position_state": position,
        "config": asdict(config),
        "trade_log": [asdict(t) for t in trades],
        "benchmark_buy_hold_pct": round((_slip(candles[-1].close, "long", config.slippage_rate, False) / _slip(candles[0].open, "long", config.slippage_rate, True) * (1 - 2 * config.fee_rate) - 1) * 100, 2),
    }
    metric_curve = [point for point in curve if trade_start_ms is None or point[0] >= trade_start_ms]
    result.update(performance_metrics(config.initial_equity, metric_curve, trades))
    return result


def _aggregate(bucket: list[Candle]) -> Candle:
    return Candle(bucket[0].open_time_ms, bucket[0].open, max(c.high for c in bucket), min(c.low for c in bucket), bucket[-1].close, sum(c.volume for c in bucket))


def _slip(price: float, side: str, rate: float, entry: bool) -> float:
    buy = (side == "long" and entry) or (side == "short" and not entry)
    return price * (1 + rate if buy else 1 - rate)


def _marked_equity(cash_equity: float, position: dict | None, price: float, fee_rate: float) -> float:
    if not position:
        return cash_equity
    gross = ((price - position["entry"]) if position["side"] == "long" else (position["entry"] - price)) * position["quantity"]
    expected_exit_fee = price * position["quantity"] * fee_rate
    return cash_equity + gross - expected_exit_fee


def _rolling_volatility(closes: list[float], period: int) -> list[float]:
    out = [float("nan")] * len(closes)
    returns = [float("nan")] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    for i in range(period, len(closes)):
        window = returns[i - period + 1:i + 1]
        out[i] = pstdev(window)
    return out
