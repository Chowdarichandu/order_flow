"""Typed contracts for EXPLORATORY public-candle research, separate from live feed."""
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MarketPanel:
    """Observed OHLCV on a UTC-aware bar-start grid; NaN means missing, never filled.

    Index instruments are reference inputs only. Daily decisions become available
    at the session close, hourly decisions at their bar close; execution is always
    the following observed grid row's open. Calendar dates are displayed in IST.
    """
    times: pd.DatetimeIndex
    symbols: tuple[str, ...]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    tradable: np.ndarray
    sector_by_symbol: Mapping[str, str] = field(default_factory=dict)
    holidays: frozenset[date] = frozenset()
    nifty50_symbols: tuple[str, ...] = ()
    holiday_events: tuple[dict[str, Any], ...] = ()
    holiday_years: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.times.tz is None or not self.times.is_monotonic_increasing or not self.times.is_unique:
            raise ValueError('panel timestamps must be aware, ordered and unique')
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError('symbol labels must be unique')
        shape = (len(self.times), len(self.symbols))
        if any(np.asarray(getattr(self, name)).shape != shape for name in ('open','high','low','close','volume')):
            raise ValueError('all OHLCV arrays must match time by symbol dimensions')
        if np.asarray(self.tradable).shape != (len(self.symbols),):
            raise ValueError('tradable mask must match symbol dimension')


@dataclass(frozen=True)
class StrategyVariant:
    """A preregistered set of causal signal parameters, counted before evaluation."""
    id: str
    family: int | str
    parameters: Mapping[str, Any]
    timeframe: str
