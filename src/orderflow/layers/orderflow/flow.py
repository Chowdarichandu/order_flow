"""BOOTSTRAP 4.1 causal absorption, exhaustion, divergence, VPIN and impact.

Snapshot flow is an ESTIMATE. Ambiguous dominance and return conventions are
explicit arguments, rather than inferred configuration defaults.
"""
from collections import deque
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import chain
from math import log
from typing import Literal

import numpy as np
import pyarrow as pa

from orderflow.schema import BAR_SCHEMA, TRADE_SCHEMA, FOOTPRINT_SCHEMA, FEATURE_SCHEMA, EVENT_SCHEMA


def _cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    return value


def _refs(rows: list[dict]) -> list[dict]:
    return [dict(record_id=r.get('bar_id', f"{r['instrument_key']}:{r.get('sequence', 0)}"), available_at=r['available_at']) for r in rows]


def _feature(row: dict, name: str, value: float | None, *, available_at: datetime,
             inputs: list[dict], n: int, unknown_share: float | None = None,
             r_squared: float | None = None, flags: list[str] | None = None,
             window_start: datetime | None = None, window_end: datetime | None = None) -> dict:
    return dict(symbol=row['symbol'], instrument_key=row['instrument_key'], session_date=row['session_date'],
        minute=available_at, name=name, level=None, value=value, r_squared=r_squared, n=n,
        unknown_share=unknown_share, window_start=window_start, window_end=window_end,
        source=row['source'], method='ESTIMATE', confidence='LOW', flags=sorted(set(flags or []) | set(row['flags'])),
        available_at=available_at, inputs=inputs)


def vpin(trades: pa.Table, *, bucket_size: int | float | Decimal | Mapping[tuple[str,date],int | float | Decimal],
         as_of: datetime, rolling_buckets: int = 50) -> pa.Table:
    """Fixed-day buckets: mean |buy-sell|/V; UNKNOWN split equally, share reported.

    The owner supplies V from trailing 20-session average daily volume / 50,
    either one size or a mapping keyed by (instrument_key, session_date).
    Fractional V is retained exactly with decimal arithmetic.
    Incomplete buckets remain unreported. Buckets and trailing mean reset each
    symbol-day. One snapshot may complete multiple buckets at its receipt time.
    """
    _cutoff(as_of)
    if not trades.schema.equals(TRADE_SCHEMA):
        raise ValueError('canonical trade contract required')
    def checked_size(value: int | float | Decimal) -> Decimal:
        result=Decimal(str(value))
        if not result.is_finite() or result<=0:
            raise ValueError('positive finite fixed bucket size required')
        return result
    if rolling_buckets < 1:
        raise ValueError('positive rolling buckets required')
    sizes={key:checked_size(value) for key,value in bucket_size.items()} if isinstance(bucket_size,Mapping) else None
    fixed=checked_size(bucket_size) if sizes is None else None
    output=[];states={};last_available={}
    for row in chain.from_iterable(batch.to_pylist() for batch in trades.to_batches(max_chunksize=10000)):
        if row['available_at'] > as_of:
            continue
        if row['volume'] < 0 or row['side'] not in {'BUY', 'SELL', 'UNKNOWN'}:
            raise ValueError('invalid volume or aggressor side')
        key=(row['instrument_key'],row['session_date'])
        if key in last_available and row['available_at'] < last_available[key]:
            raise ValueError('trade availability must be ordered per symbol-day')
        last_available[key]=row['available_at']
        if {'DUPLICATE','OUT_OF_ORDER'} & set(row['flags']):
            continue
        if sizes is not None and key not in sizes:
            raise ValueError('missing fixed bucket size for symbol-day')
        size=sizes[key] if sizes is not None else fixed
        state=states.setdefault(key,dict(filled=Decimal(0),buy=Decimal(0),sell=Decimal(0),unknown=Decimal(0),refs=[],flags=set(),start=None,
            buckets=deque(maxlen=rolling_buckets)))
        remaining=Decimal(row['volume'])
        while remaining:
            amount=min(size-state['filled'],remaining)
            state['start']=state['start'] or row['available_at']
            state['filled']+=amount;remaining-=amount
            if row['side']=='UNKNOWN':
                state['buy']+=amount/2;state['sell']+=amount/2;state['unknown']+=amount
            else:
                state['buy' if row['side']=='BUY' else 'sell']+=amount
            state['refs'].extend(_refs([row]));state['flags'].update(row['flags'])
            if state['filled']==size:
                state['buckets'].append(dict(imbalance=float(abs(state['buy']-state['sell'])/size),
                    unknown=float(state['unknown']/size), refs=state['refs'], flags=state['flags'], start=state['start']))
                buckets=state['buckets']
                output.append(_feature(row,'VPIN',sum(b['imbalance'] for b in buckets)/len(buckets),
                    available_at=row['available_at'],inputs=[ref for b in buckets for ref in b['refs']],n=len(buckets),
                    unknown_share=sum(b['unknown'] for b in buckets)/len(buckets),
                    flags=sorted(set().union(*(b['flags'] for b in buckets))),window_start=buckets[0]['start'],window_end=row['available_at']))
                state.update(filled=Decimal(0),buy=Decimal(0),sell=Decimal(0),unknown=Decimal(0),refs=[],flags=set(),start=None)
    return pa.Table.from_pylist(output,schema=FEATURE_SCHEMA)


def kyle_lambda(bars: pa.Table, *, as_of: datetime, return_definition: Literal['simple','log'],
                window_minutes: int = 30) -> pa.Table:
    """OLS with intercept: one-minute mid return on same-minute signed delta.

    Simple return is mid_t/mid_(t-1)-1; log return is log(mid_t/mid_(t-1)).
    Only adjacent closed 1m bars form returns. The rolling window is clock time,
    not a substitution of 30 observed bars across gaps. Null mid is never LTP.
    """
    _cutoff(as_of)
    if not bars.schema.equals(BAR_SCHEMA):
        raise ValueError('canonical bar contract required')
    if return_definition not in {'simple','log'} or window_minutes < 1:
        raise ValueError('explicit simple/log convention and positive window required')
    groups={}
    for row in bars.to_pylist():
        if row['bar_kind']!='TIME' or row['timeframe_minutes']!=1:
            continue
        if row['available_at']>as_of or row['bar_end']>as_of:
            continue
        groups.setdefault((row['instrument_key'],row['session_date']),[]).append(row)
    output=[]
    for rows in groups.values():
        rows.sort(key=lambda r:(r['bar_end'],r['available_at'],r['bar_id']))
        previous=None;pairs=deque();observations=deque()
        for row in rows:
            flags=set(row['flags']);pair=None
            if {'DUPLICATE','OUT_OF_ORDER'} & flags:
                continue
            # A later-arriving previous bar must never revise an earlier value.
            if previous is not None and previous['available_at'] <= row['available_at']:
                if previous['bar_end'] != row['bar_start']:
                    flags.add('GAP')
                elif previous['mid_close'] is None or row['mid_close'] is None:
                    flags.add('MISSING_MID')
                elif previous['mid_close']<=0 or row['mid_close']<=0:
                    flags.add('INVALID_MID')
                else:
                    ratio=float(row['mid_close']/previous['mid_close'])
                    pair=(float(row['delta']),ratio-1 if return_definition=='simple' else log(ratio),row,previous)
            elif previous is not None:
                flags.add('LATE_PREVIOUS_BAR')
            cutoff=row['bar_end']-timedelta(minutes=window_minutes)
            observations.append((row['bar_end'],flags))
            while observations and observations[0][0]<=cutoff:
                observations.popleft()
            if pair is not None:
                pairs.append(pair)
            while pairs and pairs[0][2]['bar_end']<=cutoff:
                pairs.popleft()
            flags=set().union(*(f for _,f in observations));slope=r2=None
            x=np.array([p[0] for p in pairs]);y=np.array([p[1] for p in pairs]);n=len(pairs)
            if n<2:
                flags.add('INSUFFICIENT_OBSERVATIONS')
            else:
                dx=x-x.mean();dy=y-y.mean();xx=float(dx@dx);yy=float(dy@dy)
                if xx==0:
                    flags.add('ZERO_DELTA_VARIANCE')
                else:
                    xy=float(dx@dy);slope=xy/xx
                    if yy==0:
                        flags.add('ZERO_RETURN_VARIANCE')
                    else:
                        r2=min(1.,max(0.,xy*xy/(xx*yy)))
            refs={}
            for pair in pairs:
                for source in pair[2:]:
                    refs[source['bar_id']]=source
            refs[row['bar_id']]=row
            output.append(_feature(row,'KYLE_LAMBDA',slope,available_at=row['available_at'],inputs=_refs(list(refs.values())),
                n=n,r_squared=r2,flags=sorted(flags),window_start=cutoff,window_end=row['bar_end']))
            previous=row
    return pa.Table.from_pylist(output,schema=FEATURE_SCHEMA)


def _event(kind: str, side: str, price: Decimal, origin: dict, sources: list[dict], strength: float | None) -> dict:
    available=max(r['available_at'] for r in sources);confirmed=max(r['bar_end'] for r in sources)
    flags=set().union(*(set(r['flags']) for r in sources))
    chronological=sorted({r['bar_id']:r for r in sources}.values(),key=lambda r:r['bar_start'])
    if origin['bar_kind']=='TIME' and any(a['bar_end']!=b['bar_start'] for a,b in zip(chronological,chronological[1:])):
        flags.add('GAP')
    return dict(symbol=origin['symbol'],instrument_key=origin['instrument_key'],session_date=origin['session_date'],
        event_id=f"{origin['instrument_key']}:{origin['session_date']}:{kind}:{side}:{origin['bar_id']}:{price}",
        event_type=kind,occurred_at=origin['bar_end'],confirmed_at=confirmed,price=price,side=side,strength=strength,zone_id=None,
        source=origin['source'],method='ESTIMATE',confidence='LOW',flags=sorted(flags),
        available_at=max(available,confirmed),inputs=_refs(sources))


def flow_events(bars: pa.Table, footprints: pa.Table, *, tick_size: Decimal, dominant_fraction: float, as_of: datetime,
                absorption_bars: int = 3, radius_ticks: int = 1, volume_factor: float = 3,
                max_extension_ticks: int = 2, extreme_bars: int = 20, delta_percentile: float = 90,
                confirmation_bars: int = 3, swing_bars_each_side: int = 2) -> pa.Table:
    """Absorption W bars; exhaustion M closes; divergence of confirmed fractals.

    Dominance is explicitly a fraction of all nearby volume, including UNKNOWN;
    SELL flow into support produces BUY absorption, BUY into resistance SELL.
    Median uses per-price volume summed over W bars. New extremes are strict,
    compared with preceding N bars; the candidate's day-so-far delta percentile
    includes the candidate. Fractals require strict extrema on both sides.
    """
    _cutoff(as_of)
    if not bars.schema.equals(BAR_SCHEMA) or not footprints.schema.equals(FOOTPRINT_SCHEMA):
        raise ValueError('canonical bar and footprint contracts required')
    if tick_size<=0 or not .5<dominant_fraction<=1 or min(absorption_bars,extreme_bars,confirmation_bars,swing_bars_each_side)<1:
        raise ValueError('positive windows/tick and dominance fraction > .5 required')
    if volume_factor<=0 or radius_ticks<0 or max_extension_ticks<0 or not 0<=delta_percentile<=100:
        raise ValueError('invalid flow parameters')
    groups={};fp={}
    for row in bars.to_pylist():
        if row['available_at']>as_of or row['bar_end']>as_of:
            continue
        if {'DUPLICATE','OUT_OF_ORDER'}&set(row['flags']):
            continue
        groups.setdefault((row['instrument_key'],row['session_date'],row['bar_kind'],row['timeframe_minutes'],row['volume_target']),[]).append(row)
    for level in footprints.to_pylist():
        if level['available_at']<=as_of:
            fp.setdefault((level['instrument_key'],level['session_date'],level['bar_id']),[]).append(level)
    output=[]
    for rows in groups.values():
        rows.sort(key=lambda r:(r['bar_end'],r['available_at'],r['bar_id']))
        for i,row in enumerate(rows):
            # Do not evaluate a past endpoint using a source which arrived later.
            if i+1>=absorption_bars:
                window=rows[i+1-absorption_bars:i+1]
                if all(r['available_at']<=row['available_at'] for r in window):
                    levels={};level_refs=[]
                    for bar in window:
                        for level in fp.get((bar['instrument_key'],bar['session_date'],bar['bar_id']),[]):
                            if level['available_at']>row['available_at']:
                                continue
                            level_refs.append(level)
                            quantity=levels.setdefault(level['price'],[0,0,0])
                            for j,name in enumerate(('bid_volume','ask_volume','unknown_volume')):
                                quantity[j]+=level[name]
                    median=float(np.median([sum(v) for v in levels.values()])) if levels else 0
                    for price in levels:
                        near=[v for p,v in levels.items() if abs(p-price)<=tick_size*radius_ticks]
                        sell=sum(v[0] for v in near);buy=sum(v[1] for v in near);unknown=sum(v[2] for v in near);total=sell+buy+unknown
                        if total<=0 or total<volume_factor*median:
                            continue
                        if sell/total>=dominant_fraction and min(b['low'] for b in window)>=price-tick_size*max_extension_ticks:
                            output.append(_event('ABSORPTION','BUY',price,row,window,total/median if median else None))
                        if buy/total>=dominant_fraction and max(b['high'] for b in window)<=price+tick_size*max_extension_ticks:
                            output.append(_event('ABSORPTION','SELL',price,row,window,total/median if median else None))
                        # Footprint provenance is necessary when available after bar close.
                        for event in output[-2:]:
                            if event['event_type']=='ABSORPTION' and event['occurred_at']==row['bar_end'] and event['price']==price:
                                event['inputs'] += [dict(record_id=f"{l['bar_id']}:{l['price']}",available_at=l['available_at']) for l in level_refs]
                                event['flags']=sorted(set(event['flags']) | set().union(*(set(l['flags']) for l in level_refs)))
            if i>=extreme_bars and i+confirmation_bars<len(rows):
                past=rows[i-extreme_bars:i];future=rows[i+1:i+1+confirmation_bars]
                sources=past+[row]+future
                # Detection at candidate time uses only bars available then.
                if any(r['available_at']>row['available_at'] for r in past):
                    continue
                day=[r for r in rows[:i+1] if r['available_at']<=row['available_at']]
                threshold=float(np.percentile([abs(r['delta']) for r in day],delta_percentile))
                if abs(row['delta'])>=threshold:
                    if row['high']>max(r['high'] for r in past) and max(r['high'] for r in future)<=row['high']:
                        output.append(_event('EXHAUSTION','SELL',row['high'],row,sources,abs(row['delta'])))
                    if row['low']<min(r['low'] for r in past) and min(r['low'] for r in future)>=row['low']:
                        output.append(_event('EXHAUSTION','BUY',row['low'],row,sources,abs(row['delta'])))
        swing_previous={};s=swing_bars_each_side
        for i in range(s,len(rows)-s):
            row=rows[i];window=rows[i-s:i+s+1]
            others=window[:s]+window[s+1:]
            for field,side in [('high','SELL'),('low','BUY')]:
                extreme=all(row[field]>r[field] for r in others) if field=='high' else all(row[field]<r[field] for r in others)
                if not extreme:
                    continue
                previous=swing_previous.get(field)
                if previous:
                    old,old_window=previous
                    divergent=(row['high']>old['high'] and row['cvd']<old['cvd']) if field=='high' else (row['low']<old['low'] and row['cvd']>old['cvd'])
                    if divergent:
                        output.append(_event('DELTA_DIVERGENCE',side,row[field],row,old_window+window,float(abs(row['cvd']-old['cvd']))))
                swing_previous[field]=(row,window)
    output=[event for event in output if event['available_at']<=as_of]
    output.sort(key=lambda e:(e['available_at'],e['event_id']))
    return pa.Table.from_pylist(output,schema=EVENT_SCHEMA)


def vpin_bucket_parameters(candles:pa.Table,*,for_session:date,as_of:datetime,
                           lookback_sessions:int=20,buckets_per_day:int=50) -> pa.Table:
    """BOOTSTRAP 4.1: fixed V = preceding 20-session mean daily volume / 50.

    Only already available, closed candles before for_session contribute. Each
    daily total requires full nonoverlapping regular NSE coverage, 09:15–15:30
    IST (375 minutes). Missing/incomplete history yields null, never an invented
    partial-day total. Uses supplied complete session dates, without guessing
    holidays; observed weekday gaps are flagged as unverified session gaps.
    Parameter publication must occur at or before the requested session open.
    """
    from datetime import time
    from zoneinfo import ZoneInfo
    from orderflow.auth.core import aware
    from orderflow.schema import CANDLE_SCHEMA
    cutoff=aware(as_of)
    if not isinstance(for_session,date) or isinstance(for_session,datetime):
        raise ValueError('for_session must be a date')
    if not candles.schema.equals(CANDLE_SCHEMA):
        raise ValueError('canonical candle contract required')
    if lookback_sessions<1 or buckets_per_day<1:
        raise ValueError('positive lookback and daily bucket count required')
    zone=ZoneInfo('Asia/Kolkata')
    opening=aware(datetime.combine(for_session,time(9,15),tzinfo=zone))
    if cutoff>opening:
        raise ValueError('daily VPIN bucket size must be fixed by session open')
    groups={}
    for batch in candles.to_batches(max_chunksize=10000):
        for row in batch.to_pylist():
            published=max([row['available_at']]+[ref['available_at'] for ref in row['inputs']])
            if published>cutoff or row['bar_end']>cutoff or row['session_date']>=for_session:
                continue
            group=groups.setdefault((row['symbol'],row['instrument_key']),{})
            group.setdefault(row['session_date'],[]).append(row)
    output=[]
    for (symbol,key),sessions in sorted(groups.items()):
        complete=[];flags=set()
        for day,rows in sorted(sessions.items()):
            start=aware(datetime.combine(day,time(9,15),tzinfo=zone))
            covered=set();volume=0;unique={};refs=[];valid=True;methods=[]
            for row in sorted(rows,key=lambda r:(r['bar_start'],r['bar_end'],r['available_at'])):
                flags.update(row['flags'])
                if {'DUPLICATE','OUT_OF_ORDER'}&set(row['flags']):
                    flags.add('DUPLICATE_CANDLE' if 'DUPLICATE' in row['flags'] else 'OUT_OF_ORDER_CANDLE')
                    continue
                identity=(row['bar_start'],row['bar_end'])
                if identity in unique:
                    flags.add('DUPLICATE_CANDLE')
                    old=unique[identity]
                    if any(row[name]!=old[name] for name in ('open','high','low','close','volume')):
                        flags.add('DAILY_VOLUME_CONFLICT');valid=False
                    continue
                unique[identity]=row
                offset=(row['bar_start']-start).total_seconds()/60
                length=(row['bar_end']-row['bar_start']).total_seconds()/60
                if not offset.is_integer() or not length.is_integer() or length<=0 or offset<0 or offset+length>375 or row['timeframe_minutes']!=length or row['volume']<0:
                    flags.add('INVALID_SESSION_CANDLE');valid=False;continue
                minutes=set(range(int(offset),int(offset+length)))
                if covered&minutes:
                    flags.add('OVERLAPPING_CANDLES');valid=False;continue
                if 'GAP' in row['flags']:
                    valid=False
                covered.update(minutes);volume+=row['volume'];methods.append(row['method'])
                refs.append(dict(record_id=f"{key}:{row['bar_start'].isoformat()}",available_at=row['available_at']))
                refs.extend(row['inputs'])
            if valid and covered==set(range(375)):
                complete.append(dict(day=day,volume=volume,refs=refs,methods=methods,start=start,end=start+timedelta(minutes=375)))
            else:
                flags.add('INCOMPLETE_SESSION')
        selected=complete[-lookback_sessions:]
        if len(selected)<lookback_sessions:
            flags.add('INSUFFICIENT_DAILY_HISTORY');value=None
        else:
            value=float(sum(Decimal(session['volume']) for session in selected)/Decimal(lookback_sessions)/Decimal(buckets_per_day))
            if value<=0:
                flags.add('ZERO_DAILY_VOLUME');value=None
        # Without an official calendar, an absent weekday could be a holiday or
        # missing history. Preserve this uncertainty; never manufacture a day.
        observed=[session['day'] for session in selected]+([for_session] if selected else [])
        for left,right in zip(observed,observed[1:]):
            day=left+timedelta(days=1)
            while day<right:
                if day.weekday()<5:
                    flags.add('UNVERIFIED_SESSION_GAP');break
                day+=timedelta(days=1)
        refs=[ref for session in selected for ref in session['refs']]
        methods=[method for session in selected for method in session['methods']]
        output.append(dict(symbol=symbol,instrument_key=key,session_date=for_session,minute=opening,name='VPIN_BUCKET_SIZE',level=None,
            value=value,r_squared=None,n=len(selected),unknown_share=None,window_start=selected[0]['start'] if selected else None,
            window_end=selected[-1]['end'] if selected else None,source='history',method='APPROXIMATE' if 'APPROXIMATE' in methods else 'EXACT',
            confidence='HIGH' if value is not None and not flags else 'LOW',flags=sorted(flags),available_at=cutoff,inputs=refs))
    return pa.Table.from_pylist(output,schema=FEATURE_SCHEMA)
