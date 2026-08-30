from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def time(self) -> datetime:
        return datetime.fromtimestamp(self.open_time_ms / 1000, tz=timezone.utc)


@dataclass(frozen=True)
class Trade:
    side: str
    entry_time_ms: int
    exit_time_ms: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    fees: float
    funding: float
    reason: str


@dataclass(frozen=True)
class FundingRate:
    funding_time_ms: int
    rate: float
