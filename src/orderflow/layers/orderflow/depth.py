"""Exact BOOTSTRAP 4.1 depth definitions and timestamped feature producer."""
from collections import deque
from collections.abc import Iterable, Iterator
from typing import Any
import pyarrow as pa
from orderflow.schema import TICK_SCHEMA,FEATURE_SCHEMA


def depth_imbalance(bids:list[dict],asks:list[dict],*,levels:int) -> float|None:
    """DI_L=(sum bid_qty-sum ask_qty)/(sum bid_qty+sum ask_qty), levels 1..L."""
    if levels<1:raise ValueError('positive levels required')
    bid=sum(q['quantity'] for q in bids[:levels]);ask=sum(q['quantity'] for q in asks[:levels])
    return (bid-ask)/(bid+ask) if bid+ask else None


def ofi(previous:dict,current:dict) -> float:
    """Cont-Kukanov-Stoikov e_n with all four inclusive quote-price indicators."""
    pb,qb=previous['bid']['price'],previous['bid']['quantity']
    pa_,qa=previous['ask']['price'],previous['ask']['quantity']
    nb,nqb=current['bid']['price'],current['bid']['quantity']
    na,nqa=current['ask']['price'],current['ask']['quantity']
    return (nb>=pb)*nqb-(nb<=pb)*qb-(na<=pa_)*nqa+(na>=pa_)*qa


def multi_ofi(previous:dict,current:dict,*,average_depth:list[float]) -> dict[str,Any]:
    """Per-level e_n and sum(e_m/trailing mean depth_m), using supplied past depths."""
    count=min(len(previous['bids']),len(previous['asks']),len(current['bids']),len(current['asks']),len(average_depth))
    values=[ofi(dict(bid=previous['bids'][i],ask=previous['asks'][i]),
                dict(bid=current['bids'][i],ask=current['asks'][i])) for i in range(count)]
    normalized=[value/average_depth[i] if average_depth[i]>0 else None for i,value in enumerate(values)]
    return dict(per_level=values,normalized_per_level=normalized,
                normalized_sum=sum(normalized) if normalized and all(v is not None for v in normalized) else None)


def sweep(previous:dict,current:dict,*,traded_volume:int,k:int=3) -> str|None:
    """Best ask/bid moves through >=k previously displayed levels with volume>0."""
    if traded_volume<=0:return None
    if previous['asks'] and current['asks']:
        ask=current['asks'][0]['price']
        if sum(level['price']<ask for level in previous['asks'])>=k:return 'BUY'
    if previous['bids'] and current['bids']:
        bid=current['bids'][0]['price']
        if sum(level['price']>bid for level in previous['bids'])>=k:return 'SELL'
    return None


def iceberg(snapshots:list[dict],*,factor:float=3,min_refills:int=2) -> dict[str,Any]:
    """Stationary best level, traded>F*max displayed, >=2 observed quantity refills."""
    if factor<=0 or min_refills<1:raise ValueError('invalid iceberg parameters')
    if not snapshots:return dict(detected=False,refills=0,method='HEURISTIC')
    prices={row['price'] for row in snapshots}
    refills=sum(right['quantity']>left['quantity'] for left,right in zip(snapshots,snapshots[1:]))
    volume=sum(row['traded_volume'] for row in snapshots)
    maximum=max(row['quantity'] for row in snapshots)
    return dict(detected=len(prices)==1 and volume>factor*maximum and refills>=min_refills,
                refills=refills,method='HEURISTIC')


def _depth_feature_rows(rows: Iterable[dict[str, Any]], *, levels: int = 5, trailing_window: int,
                   iceberg_window: int, sweep_levels: int = 3,
                   iceberg_factor: float = 3, min_refills: int = 2) -> Iterator[dict[str, Any]]:
    """Produce causal DI, snapshot e_n, minute interval OFI, sweeps and icebergs.

    OFI is e_n per level; OFI_INTERVAL is its developing sum in the current
    UTC receipt-minute, including the boundary transition from the prior minute.
    Missing transitions remain null, never zero-filled. OFI_NORMALIZED divides
    e_n by trailing mean (bid_qty + ask_qty)/2, including the current snapshot.
    MULTI_OFI_NORMALIZED sums those normalized values only when all requested
    levels exist. Windows are explicit because BOOTSTRAP gives no lengths.

    Stale/duplicate snapshots produce flagged nulls and do not update state.
    Estimated snapshot vtt volume is attributed to the observed last price for
    HEURISTIC iceberg detection; resets break that heuristic's window.
    """
    if (min(levels, trailing_window, iceberg_window, sweep_levels) < 1
            or iceberg_factor <= 0 or min_refills < 1):
        raise ValueError('canonical ticks and positive parameters required')
    states: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        output: list[dict[str, Any]] = []
        key = (row['instrument_key'], row['session_date'])
        state = states.setdefault(key, dict(
            previous=None, depth=deque(maxlen=trailing_window),
            BUY=deque(maxlen=iceberg_window), SELL=deque(maxlen=iceberg_window),
            interval=None, interval_sum=[0.0] * levels,
            interval_valid=[False] * levels, interval_inputs=[]))
        previous = state['previous']
        flags = set(row['flags'])
        if previous and (row['receipt_ts'] < previous['receipt_ts']
                         or (row['exchange_ts'] is not None and previous['exchange_ts'] is not None
                             and row['exchange_ts'] < previous['exchange_ts'])
                         or row['sequence'] < previous['sequence']):
            flags.add('OUT_OF_ORDER')
        if previous and row['sequence'] == previous['sequence']:
            flags.add('DUPLICATE')
        stale = bool({'DUPLICATE', 'OUT_OF_ORDER'} & flags)
        count = min(len(row['bids']), len(row['asks']), levels)
        if count < levels:
            flags.add('PARTIAL_DEPTH')
        minute = row['receipt_ts'].replace(second=0, microsecond=0)
        reset = 'VOLUME_RESET' in flags
        volume = 0
        if previous and row['vtt'] is not None and previous['vtt'] is not None:
            difference = row['vtt'] - previous['vtt']
            reset = reset or difference < 0
            if reset:
                flags.add('VOLUME_RESET')
            else:
                volume = difference

        def emit(name: str, value: float | None, level: int | None = None,
                 method: str = 'ESTIMATE', inputs: list[dict] | None = None,
                 window_start=None) -> None:
            """Attach only actual contributing snapshots available by this receipt."""
            refs = inputs if inputs is not None else [row]
            unique = {(r['instrument_key'], r['sequence'], r['receipt_ts']): r for r in refs}
            output.append(dict(
                symbol=row['symbol'], instrument_key=row['instrument_key'],
                session_date=row['session_date'], minute=row['receipt_ts'],
                name=name, level=level, value=value, r_squared=None, n=None,
                unknown_share=None, window_start=window_start,
                window_end=row['receipt_ts'], source=row['source'], method=method,
                confidence='LOW', flags=sorted(flags), available_at=row['receipt_ts'],
                inputs=[dict(record_id=f"{r['instrument_key']}:{r['sequence']}",
                             available_at=r['receipt_ts']) for r in unique.values()]))

        emit(f'DI_{levels}', None if stale or not count else
             depth_imbalance(row['bids'], row['asks'], levels=levels))
        if stale:
            for m in range(1, levels + 1):
                emit('OFI', None, m)
                emit('OFI_NORMALIZED', None, m)
                emit('OFI_INTERVAL', None, m, window_start=minute)
            emit('MULTI_OFI_NORMALIZED', None)
            yield from output
            continue

        if minute != state['interval']:
            state.update(interval=minute, interval_sum=[0.0] * levels,
                         interval_valid=[True] * levels, interval_inputs=[])
        state['depth'].append(row)
        average = []
        for i in range(count):
            values = [(r['bids'][i]['quantity'] + r['asks'][i]['quantity']) / 2
                      for r in state['depth']
                      if min(len(r['bids']), len(r['asks'])) > i]
            average.append(sum(values) / len(values))
        if previous:
            result = multi_ofi(previous, row, average_depth=average)
            values = result['per_level']
            normalized = result['normalized_per_level']
        else:
            values, normalized = [], []
        pair = [previous, row] if previous else [row]
        state['interval_inputs'].extend(pair)
        # Keep one reference per contributing receipt, bounding minute provenance.
        state['interval_inputs'] = list({
            (r['sequence'], r['receipt_ts']): r
            for r in state['interval_inputs']}.values())
        for i in range(levels):
            value = values[i] if i < len(values) else None
            norm = normalized[i] if i < len(normalized) else None
            emit('OFI', value, i + 1, inputs=pair)
            emit('OFI_NORMALIZED', norm, i + 1,
                 inputs=list(state['depth']) + pair)
            if value is None:
                # The first session snapshot has no transition; subsequent
                # valid transitions may still start the interval's sum.
                if previous:
                    state['interval_valid'][i] = False
            else:
                state['interval_sum'][i] += value
            interval_value = (state['interval_sum'][i]
                              if value is not None and state['interval_valid'][i]
                              else None)
            emit('OFI_INTERVAL', interval_value, i + 1,
                 inputs=state['interval_inputs'], window_start=minute)
        total = (sum(normalized) if len(normalized) == levels
                 and all(v is not None for v in normalized) else None)
        emit('MULTI_OFI_NORMALIZED', total,
             inputs=list(state['depth']) + pair)

        if previous:
            side = sweep(previous, row, traded_volume=volume, k=sweep_levels)
            if side:
                emit('BOOK_SWEEP_' + side, 1, inputs=pair)
        for side, book in [('BUY', row['asks']), ('SELL', row['bids'])]:
            if reset:
                state[side].clear()
            if not book:
                state[side].clear()
                continue
            best = book[0]
            if state[side] and state[side][-1]['price'] != best['price']:
                state[side].clear()
            state[side].append(dict(
                price=best['price'], quantity=best['quantity'],
                traded_volume=volume if row['ltp'] == best['price'] else 0,
                snapshot=row, baseline=previous))
            detection = iceberg(list(state[side]), factor=iceberg_factor,
                                min_refills=min_refills)
            if detection['detected']:
                emit('ICEBERG_' + side, 1, method='HEURISTIC',
                     inputs=[snapshot for r in state[side]
                             for snapshot in (r['baseline'], r['snapshot'])
                             if snapshot is not None],
                     window_start=state[side][0]['snapshot']['receipt_ts'])
        state['previous'] = row
        yield from output


def depth_feature_batches(tick_batches: Iterable[pa.Table], *, levels: int = 5,
                          trailing_window: int, iceberg_window: int,
                          sweep_levels: int = 3, iceberg_factor: float = 3,
                          min_refills: int = 2,
                          output_batch_size: int = 10000) -> Iterator[pa.Table]:
    """Apply section 4.1 across Arrow batches with uninterrupted bounded state.

    Output buffers have at most output_batch_size rows. Snapshot history is
    bounded by the configured windows and the current receipt-minute inputs.
    Batch boundaries never reset depth, volume, OFI interval or iceberg state.
    """
    if output_batch_size < 1:
        raise ValueError('positive output_batch_size required')

    def rows() -> Iterator[dict[str, Any]]:
        for table in tick_batches:
            if not table.schema.equals(TICK_SCHEMA):
                raise ValueError('canonical TickEvent schema required')
            for batch in table.to_batches(max_chunksize=1000):
                yield from batch.to_pylist()

    pending: list[dict[str, Any]] = []
    for row in _depth_feature_rows(rows(), levels=levels,
                                  trailing_window=trailing_window,
                                  iceberg_window=iceberg_window,
                                  sweep_levels=sweep_levels,
                                  iceberg_factor=iceberg_factor,
                                  min_refills=min_refills):
        pending.append(row)
        if len(pending) == output_batch_size:
            yield pa.Table.from_pylist(pending, schema=FEATURE_SCHEMA)
            pending.clear()
    if pending:
        yield pa.Table.from_pylist(pending, schema=FEATURE_SCHEMA)


def depth_features(ticks: pa.Table, *, levels: int = 5, trailing_window: int,
                   iceberg_window: int, sweep_levels: int = 3,
                   iceberg_factor: float = 3, min_refills: int = 2) -> pa.Table:
    """Section 4.1 depth metrics, interval OFI and events, with causal provenance.

    OFI reports snapshot e_n, OFI_INTERVAL its current receipt-minute sum,
    OFI_NORMALIZED per-level e_n/trailing mean depth, and
    MULTI_OFI_NORMALIZED their complete-level sum. See depth_feature_batches
    for the identical memory-bounded producer used over a full simulated day.
    """
    if not ticks.schema.equals(TICK_SCHEMA):
        raise ValueError('canonical TickEvent schema required')
    batches = list(depth_feature_batches(
        [ticks], levels=levels, trailing_window=trailing_window,
        iceberg_window=iceberg_window, sweep_levels=sweep_levels,
        iceberg_factor=iceberg_factor, min_refills=min_refills))
    return pa.concat_tables(batches) if batches else pa.Table.from_pylist([], schema=FEATURE_SCHEMA)
