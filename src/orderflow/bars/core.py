"""Point-in-time time/volume bars from estimated snapshot trades."""
from datetime import datetime,time,timedelta
from typing import Any
import pyarrow as pa
from orderflow.schema import TRADE_SCHEMA,BAR_SCHEMA
from orderflow.auth.core import aware
from orderflow.trades.core import _session_bounds


def _bar(rows:list[dict[str,Any]], start:datetime, end:datetime, bar_id:str,
         minutes:int|None, target:int|None, cvd:int) -> dict[str,Any]:
    """Section 4.1: delta=buy-sell; UNKNOWN is never assigned to either side."""
    first=rows[0];prices=[r['price'] for r in rows]
    buy=sum(r['volume'] for r in rows if r['side']=='BUY')
    sell=sum(r['volume'] for r in rows if r['side']=='SELL')
    unknown=sum(r['volume'] for r in rows if r['side']=='UNKNOWN')
    availability=max(end if minutes is not None else start,*[r['available_at'] for r in rows])
    return dict(symbol=first['symbol'],instrument_key=first['instrument_key'],session_date=first['session_date'],
        bar_id=bar_id,bar_kind='TIME' if minutes else 'VOLUME',bar_start=start,bar_end=end,
        timeframe_minutes=minutes,volume_target=target,open=prices[0],high=max(prices),low=min(prices),
        close=prices[-1],mid_close=next((r.get('mid_price') for r in reversed(rows) if r.get('mid_price') is not None),None),volume=buy+sell+unknown,buy_volume=buy,sell_volume=sell,
        unknown_volume=unknown,delta=buy-sell,cvd=cvd+buy-sell,source=first['source'],method='ESTIMATE',
        confidence=min((r['confidence'] for r in rows),key=lambda c:['UNKNOWN','LOW','MEDIUM','HIGH'].index(c)),
        flags=sorted({f for r in rows for f in r['flags']}),available_at=availability,
        inputs=[dict(record_id=f"{r['instrument_key']}:{r['sequence']}",available_at=r['available_at']) for r in rows])


def time_bars(trades:pa.Table,*,minutes:int,as_of:datetime,
              session_open:time=time(9,15),session_close:time=time(15,30)) -> pa.Table:
    """Section 3: 1/5/15/60m bars anchored at 09:15 IST; emit only after close.

    Half-open intervals assign a boundary trade to the next bar. Only input
    available by as_of is used, and stale/duplicate events do not affect OHLC.
    No empty gap bar or volume is invented. CVD resets each symbol/session.
    Only regular [open,close) snapshots contribute. Defaults match runtime
    config. Buckets extending beyond close remain unclosed and are omitted:
    the default final 60m bucket 15:15–16:15 is never emitted as a full bar.
    """
    cutoff=aware(as_of)
    if not trades.schema.equals(TRADE_SCHEMA) or minutes not in (1,5,15,60):
        raise ValueError('canonical trades and 1/5/15/60 minute interval required')
    groups={};bounds={}
    for row in trades.to_pylist():
        if row['available_at']>cutoff or {'DUPLICATE','OUT_OF_ORDER','OUTSIDE_SESSION'}&set(row['flags']):continue
        ts=row['exchange_ts'] or row['receipt_ts']
        day=row['session_date']
        if day not in bounds:bounds[day]=_session_bounds(day,session_open,session_close)
        anchor,closing=bounds[day]
        if not anchor<=ts<closing:continue
        offset=int((ts-anchor).total_seconds()//(minutes*60))
        start=anchor+timedelta(minutes=offset*minutes)
        end=start+timedelta(minutes=minutes)
        if end>cutoff or end>closing:continue
        key=(row['instrument_key'],row['session_date'],start,end)
        groups.setdefault(key,[]).append(row)
    output=[];cvd={}
    for key,rows in sorted(groups.items(),key=lambda pair:(pair[0][0],pair[0][1],pair[0][2])):
        symbol,day,start,end=key
        rows.sort(key=lambda r:(r['exchange_ts'] or r['receipt_ts'],r['sequence']))
        session=(symbol,day)
        bar=_bar(rows,start,end,f'{symbol}:{minutes}m:{start.isoformat()}',minutes,None,cvd.get(session,0))
        cvd[session]=bar['cvd'];output.append(bar)
    return pa.Table.from_pylist(output,schema=BAR_SCHEMA)


def volume_bars(trades:pa.Table,*,target:int,as_of:datetime,
                session_open:time=time(9,15),session_close:time=time(15,30)) -> pa.Table:
    """Section 3: complete fixed-volume bars, splitting skipped-trade snapshots.

    Snapshot splits are explicitly ESTIMATE; incomplete final buckets are not
    emitted. UNKNOWN volume remains UNKNOWN. Availability is completion receipt.
    Only regular [open,close) snapshots contribute; defaults match runtime config.
    """
    cutoff=aware(as_of)
    if target<1 or not trades.schema.equals(TRADE_SCHEMA):
        raise ValueError('positive volume target and canonical trades required')
    states={};output=[];bounds={}
    for row in trades.to_pylist():
        if row['available_at']>cutoff or {'DUPLICATE','OUT_OF_ORDER','OUTSIDE_SESSION'}&set(row['flags']):continue
        day=row['session_date']
        if day not in bounds:bounds[day]=_session_bounds(day,session_open,session_close)
        opening,closing=bounds[day]
        if not opening<=(row['exchange_ts'] or row['receipt_ts'])<closing:continue
        key=(row['instrument_key'],row['session_date'])
        state=states.setdefault(key,dict(rows=[],volume=0,cvd=0,n=0))
        remaining=row['volume']
        while remaining>0:
            amount=min(target-state['volume'],remaining)
            part=dict(row,volume=amount,flags=list(row['flags']))
            if amount!=row['volume']:part['flags'].append('SPLIT_SNAPSHOT_ESTIMATE')
            state['rows'].append(part);state['volume']+=amount;remaining-=amount
            if state['volume']==target:
                start=state['rows'][0]['exchange_ts'] or state['rows'][0]['receipt_ts']
                end=row['exchange_ts'] or row['receipt_ts']
                bar=_bar(state['rows'],start,end,f"{row['instrument_key']}:{row['session_date']}:V{target}:{state['n']}",None,target,state['cvd'])
                output.append(bar);state.update(rows=[],volume=0,cvd=bar['cvd'],n=state['n']+1)
    return pa.Table.from_pylist(output,schema=BAR_SCHEMA)


def candle_bars(candles:pa.Table,*,minutes:int,as_of:datetime,
                session_open:time=time(9,15),session_close:time=time(15,30)) -> pa.Table:
    """Section 3: history OHLCV resampling, with flow UNKNOWN and APPROXIMATE label.

    Candle volume is observed; aggressor flow is unavailable and never assigned
    to BUY/SELL. Only closed/available candles contribute. Missing minutes are
    flagged, not filled; no aggregation is emitted before its closing boundary.
    Coverage must lie wholly within the regular session. Final buckets extending
    beyond close remain unclosed and omitted, matching the live bar policy.
    """
    from orderflow.schema import CANDLE_SCHEMA
    if not candles.schema.equals(CANDLE_SCHEMA) or minutes not in (1,5,15,60):
        raise ValueError('canonical candles and supported timeframe required')
    cutoff=aware(as_of);groups={};output=[];bounds={}
    for row in candles.to_pylist():
        if row['available_at']>cutoff or row['bar_end']>cutoff:continue
        day=row['session_date']
        if day not in bounds:bounds[day]=_session_bounds(day,session_open,session_close)
        anchor,closing=bounds[day]
        if row['bar_start']<anchor or row['bar_end']>closing:continue
        offset=int((row['bar_start']-anchor).total_seconds()//(minutes*60))
        start=anchor+timedelta(minutes=offset*minutes);end=start+timedelta(minutes=minutes)
        if end>cutoff or end>closing:continue
        groups.setdefault((row['instrument_key'],row['session_date'],start,end),[]).append(row)
    for (key,day,start,end),rows in sorted(groups.items()):
        rows.sort(key=lambda row:row['bar_start'])
        flags={flag for row in rows for flag in row['flags']}
        if len({row['bar_start'] for row in rows})<minutes:flags.add('GAP')
        volume=sum(row['volume'] for row in rows if 'DUPLICATE' not in row['flags'])
        output.append(dict(symbol=rows[0]['symbol'],instrument_key=key,session_date=day,
            bar_id=f'{key}:{minutes}m:{start.isoformat()}',bar_kind='TIME',bar_start=start,bar_end=end,
            timeframe_minutes=minutes,volume_target=None,open=rows[0]['open'],high=max(r['high'] for r in rows),
            low=min(r['low'] for r in rows),close=rows[-1]['close'],mid_close=None,volume=volume,
            buy_volume=0,sell_volume=0,unknown_volume=volume,delta=0,cvd=0,source='HISTORICAL_CANDLE_V3',
            method='APPROXIMATE',confidence='UNKNOWN',flags=sorted(flags),available_at=max(end,*[r['available_at'] for r in rows]),
            inputs=[dict(record_id=f"{key}:{r['bar_start'].isoformat()}",available_at=r['available_at']) for r in rows]))
    return pa.Table.from_pylist(output,schema=BAR_SCHEMA)
