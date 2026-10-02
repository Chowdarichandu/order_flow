"""Point-in-time price levels defined in BOOTSTRAP section 4.5."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

import pyarrow as pa

from orderflow.auth.core import aware
from orderflow.schema import BAR_SCHEMA, CANDLE_SCHEMA, LEVEL_SCHEMA

IST = ZoneInfo('Asia/Kolkata')


def _clock(day: date, clock: time) -> datetime:
    return aware(datetime.combine(day, clock, IST))


def _coverage(rows: list[dict], start: datetime, end: datetime) -> bool:
    cursor = start
    for row in sorted(rows, key=lambda r: r['bar_start']):
        if row['bar_start'] > cursor:
            return False
        cursor = max(cursor, row['bar_end'])
    return cursor >= end


def levels(data: pa.Table, *, as_of: datetime,
           opening_ranges: tuple[int, ...] = (5, 15, 30),
           session_open: time = time(9, 15), session_close: time = time(15, 30),
           round_number_interval: Decimal | None = None) -> pa.Table:
    """Section 4.5: prior day H/L/C, prior calendar-week H/L, OR and gaps.

    Only closed and available bars are inspected. A prior day is the last
    supplied trading session before today's IST date; its levels become known
    after the scheduled session close and all used inputs' availability. Prior
    week means the immediately preceding Monday-to-Sunday calendar week.

    Opening ranges require complete interval coverage. Missing bars produce an
    INCOMPLETE diagnostic level rather than falsely complete high/low. Coarser
    bars that straddle a range boundary never contribute to that range.

    Gap intervals span prior close to session open. A wick reaching the prior
    close fills the gap; trading into it marks PARTIAL. The source does not
    specify a close-based fill requirement. Status changes only after the
    corresponding bar closes. Round levels are disabled unless a positive
    caller-supplied interval is provided.
    """
    cutoff = aware(as_of)
    if not (data.schema.equals(BAR_SCHEMA) or data.schema.equals(CANDLE_SCHEMA)):
        raise ValueError('levels requires the canonical bar or candle schema')
    if any(n <= 0 for n in opening_ranges):
        raise ValueError('opening range minutes must be positive')
    if round_number_interval is not None and round_number_interval <= 0:
        raise ValueError('round number interval must be positive')
    day = cutoff.astimezone(IST).date()
    week = day - timedelta(days=day.weekday())
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for batch in data.to_batches(max_chunksize=10000):
        for row in batch.to_pylist():
            if row['available_at'] <= cutoff and row['bar_end'] <= cutoff:
                if row.get('bar_kind', 'TIME') != 'TIME':
                    continue
                groups[(row['symbol'], row['instrument_key'])].append(row)
    output: list[dict] = []
    for (symbol, key), all_rows in sorted(groups.items()):
        rows = sorted(all_rows, key=lambda r: (r['bar_start'], r['available_at']))
        identities: dict[tuple, list[dict]] = defaultdict(list)
        for row in rows:
            identities[(row['session_date'], row['bar_start'], row['bar_end'])].append(row)
        for same in identities.values():
            if len(same) > 1:
                for row in same[1:]:
                    row['flags'] = sorted(set(row['flags']) | {'DUPLICATE'})
        sessions: dict[date, list[dict]] = defaultdict(list)
        for row in rows:
            sessions[row['session_date']].append(row)

        def emit(kind: str, low: Decimal, high: Decimal, used: list[dict], *,
                 created: datetime, origin: datetime | None = None, side: str = 'BOTH',
                 state: str = 'ACTIVE', flags: set[str] | None = None,
                 mitigated: datetime | None = None, timeframe: int | None = None,
                 available: datetime | None = None) -> None:
            stamp = max([created, *(r['available_at'] for r in used)]) if available is None else available
            if stamp > cutoff:
                return
            all_flags = set(flags or ())
            all_flags.update(f for r in used for f in r['flags'])
            method = 'APPROXIMATE' if any(r['method'] == 'APPROXIMATE' for r in used) else 'ESTIMATE'
            references = [dict(record_id=r.get('bar_id') or f"{key}:{r['bar_start'].isoformat()}",
                               available_at=r['available_at']) for r in used]
            output.append(dict(symbol=symbol, instrument_key=key, session_date=day,
                record_id=f'{key}:{day}:{kind}:{low}:{high}', type=kind,
                timeframe_minutes=timeframe, low=low, high=high, side=side,
                origin_at=origin or used[0]['bar_start'], created_at=created,
                invalidated_at=None, mitigated_at=mitigated, state=state,
                source='LEVELS', method=method, confidence='LOW' if all_flags else 'HIGH',
                flags=sorted(all_flags), available_at=stamp, inputs=references))

        previous = [d for d in sessions if d < day and _clock(d, session_close) <= cutoff]
        previous_rows: list[dict] = []
        if previous:
            prior = max(previous)
            previous_rows = sessions[prior]
            closing = _clock(prior, session_close)
            flags = set() if _coverage(previous_rows, _clock(prior, session_open), closing) else {'INCOMPLETE_SESSION'}
            for kind, value, side in [('PDH', max(r['high'] for r in previous_rows), 'RESISTANCE'),
                                      ('PDL', min(r['low'] for r in previous_rows), 'SUPPORT'),
                                      ('PDC', previous_rows[-1]['close'], 'BOTH')]:
                emit(kind, value, value, previous_rows, created=closing, side=side, flags=flags)
        previous_week = [r for r in rows if week-timedelta(days=7) <= r['session_date'] < week]
        if previous_week:
            # A calendar week's final possible NSE session ends Friday 15:30.
            closing = _clock(week-timedelta(days=3), session_close)
            flags = set()
            for d in {r['session_date'] for r in previous_week}:
                if not _coverage(sessions[d], _clock(d, session_open), _clock(d, session_close)):
                    flags.add('INCOMPLETE_SESSION')
            for kind, value, side in [('PWH', max(r['high'] for r in previous_week), 'RESISTANCE'),
                                      ('PWL', min(r['low'] for r in previous_week), 'SUPPORT')]:
                emit(kind, value, value, previous_week, created=closing, side=side, flags=flags)
        current = sessions.get(day, [])
        opening = _clock(day, session_open)
        for minutes in opening_ranges:
            end = opening + timedelta(minutes=minutes)
            if end > cutoff:
                continue
            chosen = [r for r in current if opening <= r['bar_start'] and r['bar_end'] <= end]
            if not chosen:
                continue
            high, low = max(r['high'] for r in chosen), min(r['low'] for r in chosen)
            if not _coverage(chosen, opening, end):
                emit(f'OR{minutes}_INCOMPLETE', low, high, chosen, created=end,
                     state='INCOMPLETE', flags={'GAP'}, timeframe=minutes)
                continue
            emit(f'OR{minutes}_HIGH', high, high, chosen, created=end,
                 side='RESISTANCE', timeframe=minutes)
            emit(f'OR{minutes}_LOW', low, low, chosen, created=end,
                 side='SUPPORT', timeframe=minutes)
        if current and current[0]['bar_start'] == opening and previous_rows:
            first = current[0]
            prior_close = previous_rows[-1]['close']
            gap_open = first['open']
            if gap_open != prior_close:
                low, high = sorted([prior_close, gap_open])
                up = gap_open > prior_close
                state, touched_at, used = 'OPEN', None, [*previous_rows, first]
                for row in current:
                    if row is not first:
                        used.append(row)
                    touched = row['low'] <= prior_close if up else row['high'] >= prior_close
                    partial = row['low'] < gap_open if up else row['high'] > gap_open
                    if touched:
                        state, touched_at = 'FILLED', row['available_at']
                        break
                    if partial:
                        state = 'PARTIAL'
                emit('GAP', low, high, used, created=first['available_at'], origin=opening,
                     side='SUPPORT' if up else 'RESISTANCE', state=state, mitigated=touched_at,
                     flags=set() if _coverage(previous_rows, _clock(previous_rows[0]['session_date'], session_open),
                         _clock(previous_rows[0]['session_date'], session_close)) else {'INCOMPLETE_SESSION'})
        if current and round_number_interval is not None:
            low, high = min(r['low'] for r in current), max(r['high'] for r in current)
            first = (low / round_number_interval).to_integral_value(rounding=ROUND_CEILING)
            last = (high / round_number_interval).to_integral_value(rounding=ROUND_FLOOR)
            for multiple in range(int(first), int(last)+1):
                price = multiple * round_number_interval
                emit('ROUND_NUMBER', price, price, current, created=current[0]['available_at'])
    return pa.Table.from_pylist(output, schema=LEVEL_SCHEMA)
