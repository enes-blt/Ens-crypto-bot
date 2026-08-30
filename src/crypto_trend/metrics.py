from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from statistics import mean, pstdev

from .models import Trade


def performance_metrics(initial: float, curve: list[tuple[int, float]], trades: list[Trade]) -> dict:
    if not curve:
        return {}
    daily: dict[str, float] = {}
    for timestamp, equity in curve:
        day = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()
        daily[day] = equity
    values = list(daily.values())
    returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1] > 0]
    volatility = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = mean(returns) / volatility * sqrt(365) if volatility else 0.0
    downside = sqrt(mean([min(r, 0) ** 2 for r in returns])) if returns else 0.0
    sortino = mean(returns) / downside * sqrt(365) if downside else 0.0
    years = max((curve[-1][0] - curve[0][0]) / (365.25 * 86_400_000), 1 / 365.25)
    final = curve[-1][1]
    cagr = (final / initial) ** (1 / years) - 1 if final > 0 else -1.0
    pnl_by_side = defaultdict(float)
    count_by_side = defaultdict(int)
    for trade in trades:
        pnl_by_side[trade.side] += trade.pnl
        count_by_side[trade.side] += 1
    return {
        "cagr_pct": round(cagr * 100, 2),
        "sharpe_365": round(sharpe, 3),
        "sortino_365": round(sortino, 3),
        "expectancy_usdt": round(mean([t.pnl for t in trades]), 2) if trades else 0.0,
        "total_fees_usdt": round(sum(t.fees for t in trades), 2),
        "total_funding_usdt": round(sum(t.funding for t in trades), 2),
        "long": {"trades": count_by_side["long"], "pnl_usdt": round(pnl_by_side["long"], 2)},
        "short": {"trades": count_by_side["short"], "pnl_usdt": round(pnl_by_side["short"], 2)},
        "yearly_returns_pct": _period_returns(curve, "%Y"),
        "monthly_returns_pct": _period_returns(curve, "%Y-%m"),
    }


def _period_returns(curve: list[tuple[int, float]], fmt: str) -> dict[str, float]:
    groups: dict[str, list[float]] = defaultdict(list)
    for timestamp, equity in curve:
        key = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime(fmt)
        groups[key].append(equity)
    return {key: round((values[-1] / values[0] - 1) * 100, 2) for key, values in groups.items() if values[0] > 0}
