"""T01 deterministic Historical Candle V3-shaped offline history."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


def candle_response(start: datetime, count: int, *,
                    scenario: str = 'normal') -> dict[str, Any]:
    """Section 2: synthesize 1-minute OHLCV, with explicit history quality faults."""
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError('start must be timezone-aware')
    if count < 0 or scenario not in {'normal', 'gap_duplicate_out_of_order'}:
        raise ValueError('invalid count or history scenario')
    candles = []
    for i in range(count):
        price = Decimal('100') + Decimal('0.05') * i
        candles.append([(start + timedelta(minutes=i)).isoformat(),
                        float(price), float(price + Decimal('0.20')),
                        float(price - Decimal('0.10')), float(price + Decimal('0.10')),
                        1000 + 10 * i, 0])
    if scenario == 'gap_duplicate_out_of_order':
        if count < 5:
            raise ValueError('fault history requires at least 5 candles')
        candles = [candles[i] for i in [0, 1, 3, 3, 2, *range(4, count)]]
    return {'status': 'success', 'data': {'candles': candles}}
