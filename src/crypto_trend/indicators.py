from collections.abc import Sequence
from math import isnan


NAN = float("nan")


def ema(values: Sequence[float], period: int) -> list[float]:
    out = [NAN] * len(values)
    if period <= 0 or len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 14) -> list[float]:
    tr: list[float] = []
    for i in range(len(close)):
        if i == 0:
            tr.append(high[i] - low[i])
        else:
            tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return _wilder(tr, period)


def adx(high: Sequence[float], low: Sequence[float], close: Sequence[float], period: int = 14) -> list[float]:
    plus_dm = [0.0]
    minus_dm = [0.0]
    tr = [high[0] - low[0]] if close else []
    for i in range(1, len(close)):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    sm_tr, sm_plus, sm_minus = _wilder(tr, period), _wilder(plus_dm, period), _wilder(minus_dm, period)
    dx = [NAN] * len(close)
    for i in range(len(close)):
        if isnan(sm_tr[i]) or sm_tr[i] == 0:
            continue
        plus_di = 100 * sm_plus[i] / sm_tr[i]
        minus_di = 100 * sm_minus[i] / sm_tr[i]
        denom = plus_di + minus_di
        dx[i] = 0.0 if denom == 0 else 100 * abs(plus_di - minus_di) / denom
    valid = [x for x in dx if not isnan(x)]
    smoothed = _wilder(valid, period)
    out = [NAN] * len(close)
    offset = next((i for i, x in enumerate(dx) if not isnan(x)), len(close))
    for j, value in enumerate(smoothed):
        if offset + j < len(out):
            out[offset + j] = value
    return out


def donchian_previous(high: Sequence[float], low: Sequence[float], period: int) -> tuple[list[float], list[float]]:
    upper, lower = [NAN] * len(high), [NAN] * len(low)
    for i in range(period, len(high)):
        upper[i] = max(high[i - period:i])
        lower[i] = min(low[i - period:i])
    return upper, lower


def _wilder(values: Sequence[float], period: int) -> list[float]:
    out = [NAN] * len(values)
    if period <= 0 or len(values) < period:
        return out
    out[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out

