"""Historical Candle V3-shaped response to the canonical candle Arrow contract."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
from orderflow.schema import CANDLE_SCHEMA


def decode_candles(response: dict[str, Any], *, symbol: str, instrument_key: str,
                   receipt_ts: datetime, timeframe_minutes: int = 1) -> pa.Table:
    """Sections 2/3: decode closed OHLCV, retaining gaps/duplicates/out-of-order.

    Candles are only knowable at max(bar close, download receipt); historical
    values must never become available retroactively at their opening timestamp.
    Return input order, flag quality issues, and never fill or drop a candle.
    """
    if receipt_ts.tzinfo is None or receipt_ts.utcoffset() is None:
        raise ValueError('receipt_ts must be timezone-aware')
    if timeframe_minutes < 1:
        raise ValueError('timeframe_minutes must be positive')
    if response.get('status') != 'success':
        raise ValueError('unsuccessful history response')
    receipt = receipt_ts.astimezone(timezone.utc)
    duration = timedelta(minutes=timeframe_minutes)
    rows = []
    seen: set[datetime] = set()
    latest: datetime | None = None
    for candle in response['data']['candles']:
        if len(candle) not in (6, 7):
            raise ValueError('invalid candle width')
        start = datetime.fromisoformat(candle[0])
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError('candle start must be timezone-aware')
        start = start.astimezone(timezone.utc)
        end = start + duration
        if end > receipt:
            raise ValueError('candle must be closed at receipt')
        op, high, low, close = (Decimal(str(v)) for v in candle[1:5])
        if not all(v.is_finite() for v in (op, high, low, close)):
            raise ValueError('nonfinite OHLC')
        if low > min(op, close) or high < max(op, close) or low > high:
            raise ValueError('invalid OHLC range')
        volume = candle[5]
        if isinstance(volume, bool) or volume < 0 or int(volume) != volume:
            raise ValueError('volume must be a nonnegative integer')
        flags = []
        if start in seen:
            flags.append('DUPLICATE')
        if latest is not None:
            if start < latest:
                flags.append('OUT_OF_ORDER')
            elif start - latest > duration:
                flags.append('GAP')
        seen.add(start)
        latest = max(latest, start) if latest else start
        rows.append(dict(symbol=symbol, instrument_key=instrument_key,
                         session_date=start.astimezone(ZoneInfo('Asia/Kolkata')).date(),
                         bar_start=start, bar_end=end, timeframe_minutes=timeframe_minutes,
                         open=op, high=high, low=low, close=close, volume=int(volume),
                         oi=candle[6] if len(candle) == 7 else None,
                         source='HISTORICAL_CANDLE_V3', method='OBSERVED', confidence='HIGH',
                         flags=flags, available_at=receipt, inputs=[]))
    return pa.Table.from_pylist(rows, schema=CANDLE_SCHEMA)
