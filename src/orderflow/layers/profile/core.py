"""BOOTSTRAP 4.2: tick/candle profile, value area, nodes, composites and IB."""
from datetime import datetime,time,timedelta,timezone
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
from typing import Any
from zoneinfo import ZoneInfo
import pyarrow as pa
from orderflow.schema import TRADE_SCHEMA,CANDLE_SCHEMA,PROFILE_SCHEMA,BAR_SCHEMA
from orderflow.auth.core import aware

D=Decimal


def profile_values(levels:dict[Decimal,float],*,tick_size:Decimal,vwap:Decimal|None,
                   value_area:float=.7) -> dict[str,Any]:
    """POC=max volume, tie nearest VWAP; expand toward larger neighboring volume.

    Cover >=70% by default. HVN/LVN are strict local extrema of a centered
    3-tick average. Price gaps have zero volume. Underspecified ties use lower
    price deterministically; this affects only exact equal-distance/volume ties.
    """
    if tick_size<=0 or not 0<value_area<=1:raise ValueError('invalid profile parameters')
    if not levels or sum(levels.values())<=0:
        return dict(poc=None,val=None,vah=None,hvn=[],lvn=[])
    if any(price%tick_size for price in levels):raise ValueError('profile price must be tick-aligned')
    prices=[];price=min(levels);maximum_price=max(levels)
    while price<=maximum_price:prices.append(price);price+=tick_size
    volumes=[float(levels.get(price,0)) for price in prices]
    maximum=max(volumes)
    candidates=[i for i,v in enumerate(volumes) if v==maximum]
    center=min(candidates,key=lambda i:(abs(prices[i]-vwap) if vwap is not None else 0,prices[i]))
    lower=upper=center;covered=volumes[center];total=sum(volumes)
    while covered<value_area*total and (lower>0 or upper<len(prices)-1):
        left=volumes[lower-1] if lower>0 else -1
        right=volumes[upper+1] if upper<len(prices)-1 else -1
        if left>=right:lower-=1;covered+=volumes[lower]
        else:upper+=1;covered+=volumes[upper]
    smooth=[sum(volumes[max(0,i-1):min(len(volumes),i+2)])/3 for i in range(len(volumes))]
    hvn=[prices[i] for i in range(1,len(prices)-1) if smooth[i]>smooth[i-1] and smooth[i]>smooth[i+1]]
    lvn=[prices[i] for i in range(1,len(prices)-1) if smooth[i]<smooth[i-1] and smooth[i]<smooth[i+1]]
    return dict(poc=prices[center],val=prices[lower],vah=prices[upper],hvn=hvn,lvn=lvn)


def session_profile(data:pa.Table,*,tick_size:Decimal,as_of:datetime,value_area:float=.7) -> pa.Table:
    """Session/developing volume per tick; candles uniform high-low APPROXIMATE.

    Live snapshot allocation is ESTIMATE. Historical VWAP uses typical HLC3;
    only available closed candles/trades are used. Each output's availability is
    its developing evaluation cutoff, never a retrospective earlier timestamp.
    """
    cutoff=aware(as_of)
    history=data.schema.equals(CANDLE_SCHEMA)
    if not history and not data.schema.equals(TRADE_SCHEMA):raise ValueError('canonical trades/candles required')
    groups={}
    for row in data.to_pylist():
        if row['available_at']>cutoff or {'DUPLICATE','OUT_OF_ORDER'}&set(row['flags']):continue
        if history and row['bar_end']>cutoff:continue
        key=(row['instrument_key'],row['session_date'])
        group=groups.setdefault(key,dict(first=row,levels={},pv=D(0),volume=0,flags=set(),inputs=[]))
        volume=row['volume'];group['volume']+=volume
        group['flags'].update(row['flags'])
        if history:
            lo=int((row['low']/tick_size).to_integral_value(rounding=ROUND_CEILING))
            hi=int((row['high']/tick_size).to_integral_value(rounding=ROUND_FLOOR))
            if hi<lo:raise ValueError('no aligned tick in candle range')
            for level in range(lo,hi+1):
                price=D(level)*tick_size
                group['levels'][price]=group['levels'].get(price,0)+volume/(hi-lo+1)
            group['pv']+=(row['high']+row['low']+row['close'])/3*volume
            record=f"{key[0]}:{row['bar_start'].isoformat()}"
        else:
            price=row['price']
            if price%tick_size:raise ValueError('trade price not tick-aligned')
            if volume:group['levels'][price]=group['levels'].get(price,0)+volume
            group['pv']+=price*volume
            record=f"{key[0]}:{row['sequence']}"
        group['inputs'].append(dict(record_id=record,available_at=row['available_at']))
    output=[]
    for (key,day),group in groups.items():
        vwap=(group['pv']/group['volume']).quantize(D('.00000001')) if group['volume'] else None
        values=profile_values(group['levels'],tick_size=tick_size,vwap=vwap,value_area=value_area)
        output.append(dict(symbol=group['first']['symbol'],instrument_key=key,session_date=day,
            minute=cutoff,profile_kind='SESSION',sessions=1,levels=[dict(price=p,volume=float(v)) for p,v in sorted(group['levels'].items())],
            vwap=vwap,ib_high=None,ib_low=None,**values,source=group['first']['source'],method='APPROXIMATE' if history else 'ESTIMATE',
            confidence='LOW',flags=sorted(group['flags']),available_at=cutoff,inputs=group['inputs']))
    return pa.Table.from_pylist(output,schema=PROFILE_SCHEMA)


def composite_profile(profiles:pa.Table,*,sessions:int,tick_size:Decimal,as_of:datetime,value_area:float=.7) -> pa.Table:
    """Composite of latest available version per session, last 5/20 by default caller."""
    if not profiles.schema.equals(PROFILE_SCHEMA) or sessions<1:raise ValueError('invalid composite input')
    cutoff=aware(as_of);latest={}
    for row in profiles.to_pylist():
        if row['available_at']>cutoff or row['profile_kind']!='SESSION':continue
        key=(row['instrument_key'],row['session_date'])
        if key not in latest or row['available_at']>latest[key]['available_at']:latest[key]=row
    groups={}
    for (key,day),row in latest.items():groups.setdefault(key,[]).append(row)
    output=[]
    for key,rows in groups.items():
        rows=sorted(rows,key=lambda row:row['session_date'])[-sessions:]
        levels={};pv=D(0);volume=0
        for row in rows:
            weight=sum(level['volume'] for level in row['levels'])
            if row['vwap'] is not None:pv+=row['vwap']*D(str(weight))
            volume+=weight
            for level in row['levels']:levels[level['price']]=levels.get(level['price'],0)+level['volume']
        vwap=(pv/D(str(volume))).quantize(D('.00000001')) if volume else None
        first=rows[-1]
        output.append(dict(symbol=first['symbol'],instrument_key=key,session_date=cutoff.astimezone(ZoneInfo('Asia/Kolkata')).date(),
            minute=cutoff,profile_kind=f'COMPOSITE_{sessions}',sessions=len(rows),levels=[dict(price=p,volume=float(v)) for p,v in sorted(levels.items())],
            vwap=vwap,ib_high=None,ib_low=None,**profile_values(levels,tick_size=tick_size,vwap=vwap,value_area=value_area),
            source=first['source'],method='APPROXIMATE' if any(r['method']=='APPROXIMATE' for r in rows) else 'ESTIMATE',
            confidence='LOW',flags=sorted({flag for r in rows for flag in r['flags']}),available_at=cutoff,
            inputs=[dict(record_id=f"{key}:{r['session_date']}:{r['minute'].isoformat()}",available_at=r['available_at']) for r in rows]))
    return pa.Table.from_pylist(output,schema=PROFILE_SCHEMA)


def naked_pocs(prior:list[dict],touches:list[Decimal],*,as_of:datetime) -> list[Decimal]:
    """Prior available POCs not touched since; caller supplies only touches as-of cutoff."""
    cutoff=aware(as_of);traded=set(touches)
    return [row['price'] for row in prior if row['available_at']<=cutoff and row['price'] not in traded]


def initial_balance(bars:pa.Table,*,as_of:datetime,minutes:int=60,multiples:list[float]|None=None) -> dict[str,Any]:
    """High/low first 60 minutes, confirmed at interval end; extensions multiply range.

    This scalar helper requires one instrument/session. Missing observations are
    flagged GAP; no empty bars or prices are filled.
    """
    if not bars.schema.equals(BAR_SCHEMA):raise ValueError('canonical bars required')
    cutoff=aware(as_of);rows=bars.to_pylist()
    if not rows:return {}
    if len({(r['instrument_key'],r['session_date']) for r in rows})!=1:raise ValueError('one symbol/session required')
    start=datetime.combine(rows[0]['session_date'],time(9,15),ZoneInfo('Asia/Kolkata')).astimezone(timezone.utc)
    end=start+timedelta(minutes=minutes)
    if cutoff<end:return {}
    chosen=[r for r in rows if start<=r['bar_start']<end and r['bar_end']<=end and r['available_at']<=cutoff]
    if not chosen:return {}
    high=max(r['high'] for r in chosen);low=min(r['low'] for r in chosen);span=high-low
    covered=sum(r['timeframe_minutes'] or 0 for r in chosen)
    return dict(high=high,low=low,range=span,available_at=max(end,*[r['available_at'] for r in chosen]),
                flags=['GAP'] if covered<minutes else [],
                extensions=[dict(multiple=m,high=high+span*D(str(m)),low=low-span*D(str(m))) for m in (multiples or [])])
