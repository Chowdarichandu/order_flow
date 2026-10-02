"""BOOTSTRAP 4.6 context; unspecified policy choices are explicit caller arguments."""
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo
import pyarrow as pa
from orderflow.auth.core import aware
from orderflow.schema import BAR_SCHEMA,FEATURE_SCHEMA,TICK_SCHEMA,LEVEL_SCHEMA,EVENT_SCHEMA,CONTEXT_SCHEMA

IST=ZoneInfo('Asia/Kolkata')


def relative_strength(stock:float,stock_base:float,sector:float,sector_base:float)->float|None:
    """Section 4.6: stock fractional return minus sector fractional return."""
    if stock_base<=0 or sector_base<=0:return None
    return stock/stock_base-sector/sector_base


def percentile_rank(value:float,history:Sequence[float],*,method:str)->float|None:
    """Explicit empirical percentile: weak <=; mean averages strict and weak ranks."""
    if method not in {'weak','mean'}:raise ValueError('percentile method must be weak or mean')
    if not history:return None
    below=sum(v<value for v in history);equal=sum(v==value for v in history)
    return 100*(below+equal*(1 if method=='weak' else .5))/len(history)


def vix_regime(percentile:float|None,*,low:float,high:float)->str|None:
    """Section 4.6: LOW/NORMAL/HIGH, with source-unspecified thresholds supplied."""
    if not 0<=low<high<=100:raise ValueError('ordered percentile thresholds required')
    if percentile is None:return None
    return 'LOW' if percentile<low else 'HIGH' if percentile>=high else 'NORMAL'


def time_category(at:datetime,*,boundaries:Mapping[str,tuple[time,time]])->str:
    """OPEN 09:15-09:45, CLOSE 14:45-15:15; middle boundaries explicitly supplied."""
    if set(boundaries)!={'MORNING','MIDDAY','AFTERNOON'}:raise ValueError('all middle-session boundaries required')
    periods={'OPEN':(time(9,15),time(9,45)),**boundaries,'CLOSE':(time(14,45),time(15,15))}
    previous=None
    for name in ('OPEN','MORNING','MIDDAY','AFTERNOON','CLOSE'):
        start,end=periods[name]
        if start>=end or (previous is not None and start!=previous):raise ValueError('contiguous ordered time intervals required')
        previous=end
    local=aware(at).astimezone(IST).time().replace(tzinfo=None)
    return next((name for name,(start,end) in periods.items() if start<=local<end),'OUTSIDE_SESSION')


def liquidity_tier(value:float|None,spread:float|None,*,value_thresholds:tuple[float,float],spread_thresholds:tuple[float,float])->int|None:
    """Section 4.6: rank median 20-session value and spread; worst dimension wins.

    Explicit thresholds: tier 1 value>=upper and spread<=lower; tier 2
    value>=lower and spread<=upper; all others tier 3. Spread is a price fraction.
    """
    if not 0<=value_thresholds[0]<value_thresholds[1] or not 0<=spread_thresholds[0]<spread_thresholds[1]:raise ValueError('ascending positive thresholds required')
    if value is None or spread is None:return None
    if value<0 or spread<0:raise ValueError('nonnegative liquidity inputs required')
    value_tier=1 if value>=value_thresholds[1] else 2 if value>=value_thresholds[0] else 3
    spread_tier=1 if spread<=spread_thresholds[0] else 2 if spread<=spread_thresholds[1] else 3
    return max(value_tier,spread_tier)


def index_regime(indices:Sequence[tuple[str,float|None,float|None]],*,policy:str)->str|None:
    """Section 4.6: two 15m structures plus positions versus session VWAP.

    The required unanimous policy emits a trend only if every index agrees in
    direction and VWAP position; disagreement is RANGE. Missing data is null.
    """
    if policy!='unanimous':raise ValueError('supported explicit index policy: unanimous')
    if not indices or any(direction is None or price is None or vwap is None for direction,price,vwap in indices):return None
    if all(d=='UP' and p>v for d,p,v in indices):return 'TREND_UP'
    if all(d=='DOWN' and p<v for d,p,v in indices):return 'TREND_DOWN'
    return 'RANGE'


def _rows(table:pa.Table,schema:pa.Schema,as_of:datetime)->list[dict]:
    if not table.schema.equals(schema):raise TypeError('canonical '+str(schema.metadata[b'orderflow.contract'])+' required')
    timestamp='receipt_ts' if schema.equals(TICK_SCHEMA) else 'available_at'
    return [r for batch in table.to_batches(max_chunksize=10000) for r in batch.to_pylist() if aware(r[timestamp])<=as_of]


def context_snapshot(bars:pa.Table,features:pa.Table,ticks:pa.Table,structures:pa.Table,events:pa.Table,*,
    as_of:datetime,sector_map:Mapping[str,str],index_symbols:tuple[str,str],vix_symbol:str,
    vix_percentile_method:str,vix_thresholds:tuple[float,float],time_boundaries:Mapping[str,tuple[time,time]],
    value_thresholds:tuple[float,float],spread_thresholds:tuple[float,float],index_policy:str,
    advancer_basis:str,universe:Sequence[str]|None=None)->pa.Table:
    """Section 4.6 canonical per-symbol point-in-time context snapshot.

    Uses closed 1m bars, confirmed 15m BOS/CHoCH levels, available VWAP features,
    T11 event IDs carry their explicit 15-minute timeframe; other-timeframe breaks
    are excluded. Uses one latest VIX reading per historical day over the preceding calendar year,
    sector returns from session open and five completed sessions earlier, and
    median daily typical-price traded value / daily median relative spread over
    the last 20 completed sessions. Incomplete history is null and flagged.
    Event records are known announcements/calendar flags; occurrence times never
    confer availability. Breadth excludes index/VIX instruments and preserves a
    missing-universe flag. All selected dependencies are timestamped references.
    """
    at=aware(as_of);day=at.astimezone(IST).date()
    category=time_category(at,boundaries=time_boundaries)
    vix_regime(None,low=vix_thresholds[0],high=vix_thresholds[1])
    percentile_rank(0,[],method=vix_percentile_method)
    liquidity_tier(None,None,value_thresholds=value_thresholds,spread_thresholds=spread_thresholds)
    index_regime([],policy=index_policy)
    if advancer_basis not in {'session_open','prior_close'}:raise ValueError('explicit advancer basis required')
    raw_bars=_rows(bars,BAR_SCHEMA,at);raw_features=_rows(features,FEATURE_SCHEMA,at)
    raw_ticks=_rows(ticks,TICK_SCHEMA,at);raw_structures=_rows(structures,LEVEL_SCHEMA,at);raw_events=_rows(events,EVENT_SCHEMA,at)
    flags=set();refs={}
    def reference(row:dict,kind:str)->None:
        timestamp=row.get('available_at',row.get('receipt_ts'))
        record=row.get('bar_id',row.get('record_id',row.get('event_id')))
        if record is None:record=f"{row['instrument_key']}:{kind}:{row.get('sequence',row.get('name',''))}:{timestamp.isoformat()}"
        refs[(record,timestamp)]=dict(record_id=record,available_at=timestamp)
        flags.update(row.get('flags',[]))
    eligible=[]
    for r in raw_bars:
        if r['bar_kind']!='TIME' or r['timeframe_minutes']!=1 or r['bar_end']>at:continue
        if {'DUPLICATE','OUT_OF_ORDER'}&set(r['flags']):flags.update(r['flags']);continue
        if r['close'] is not None and r['open'] is not None:eligible.append(r)
    daily=defaultdict(lambda:defaultdict(list))
    for r in eligible:daily[r['symbol']][r['session_date']].append(r)
    for sessions in daily.values():
        for rows in sessions.values():rows.sort(key=lambda r:(r['bar_end'],r['available_at']))
    current={s:sessions[day][-1] for s,sessions in daily.items() if day in sessions}
    first={s:sessions[day][0] for s,sessions in daily.items() if day in sessions}
    excluded=set(index_symbols)|set(sector_map.values())|{vix_symbol}
    names=sorted(set(universe) if universe is not None else set(current)-excluded)
    vwaps={}
    for r in sorted(raw_features,key=lambda r:r['available_at']):
        if r['name']=='SESSION_VWAP' and r['session_date']==day and r['value'] is not None:vwaps[r['symbol']]=r
    breadth_available=[s for s in names if s in current and s in vwaps]
    if len(breadth_available)!=len(names):flags.add('BREADTH_VWAP_MISSING')
    fraction=sum(float(current[s]['close'])>vwaps[s]['value'] for s in breadth_available)/len(breadth_available) if breadth_available and len(breadth_available)==len(names) else None
    advancers=decliners=0
    for s in names:
        if s not in current:flags.add('BREADTH_PRICE_MISSING');continue
        reference(current[s],'BAR');reference(first[s],'BAR')
        base=first[s]['open']
        if advancer_basis=='prior_close':
            prior=sorted(d for d in daily[s] if d<day)
            if not prior:flags.add('BREADTH_PRIOR_CLOSE_MISSING');continue
            baseline=daily[s][prior[-1]][-1];reference(baseline,'BAR');base=baseline['close']
        advancers+=current[s]['close']>base;decliners+=current[s]['close']<base
        if s in vwaps:reference(vwaps[s],'VWAP')
    directions={}
    for r in sorted(raw_structures,key=lambda r:r['available_at']):
        if r['timeframe_minutes']==15 and r['type'] in {'BOS','CHOCH','CHoCH'} and r['side'] in {'BUY','SELL','BULLISH','BEARISH'}:
            directions[r['symbol']]=r
    # T11's documented identity embeds timeframe immediately after instrument key.
    for r in sorted(raw_events,key=lambda r:r['available_at']):
        prefix=r['instrument_key']+':15:'
        if r['event_type'] in {'BOS','CHOCH'} and r['event_id'].startswith(prefix) and r['confirmed_at']<=at:
            previous=directions.get(r['symbol'])
            if previous is None or r['available_at']>=previous['available_at']:directions[r['symbol']]=r
    index_values=[]
    for s in index_symbols:
        struct=directions.get(s);price=current.get(s);vwap=vwaps.get(s)
        if struct:reference(struct,'STRUCTURE')
        if price:reference(price,'BAR')
        if vwap:reference(vwap,'VWAP')
        direction=('UP' if struct['side'] in {'BUY','BULLISH'} else 'DOWN') if struct else None
        index_values.append((direction,float(price['close']) if price else None,vwap['value'] if vwap else None))
    regime=index_regime(index_values,policy=index_policy)
    if regime is None:flags.add('INDEX_CONTEXT_MISSING')
    try:year_start=day.replace(year=day.year-1)
    except ValueError:year_start=day.replace(year=day.year-1,day=28)
    vix_daily={}
    spreads=defaultdict(lambda:defaultdict(list))
    for r in sorted(raw_ticks,key=lambda r:r['receipt_ts']):
        if {'DUPLICATE','OUT_OF_ORDER'}&set(r['flags']):flags.update(r['flags']);continue
        if r['exchange_ts'] is not None and r['exchange_ts']>at:flags.add('FUTURE_EXCHANGE_TIMESTAMP');continue
        if r['symbol']==vix_symbol and r['ltp'] is not None and year_start<=r['session_date']<=day:vix_daily[r['session_date']]=r
        if r['session_date']<day and r['bids'] and r['asks']:
            bid=float(r['bids'][0]['price']);ask=float(r['asks'][0]['price'])
            if ask>=bid>0:spreads[r['symbol']][r['session_date']].append(((ask-bid)/((ask+bid)/2),r))
    vix_current=vix_daily.get(day);vix_history=[r for d,r in vix_daily.items() if d<day]
    if vix_current and vix_history:
        for r in [vix_current,*vix_history]:reference(r,'VIX')
        rank=percentile_rank(float(vix_current['ltp']),[float(r['ltp']) for r in vix_history],method=vix_percentile_method)
    else:rank=None;flags.add('VIX_HISTORY_MISSING')
    volatility=vix_regime(rank,low=vix_thresholds[0],high=vix_thresholds[1])
    if vix_history and min(r['session_date'] for r in vix_history)>year_start+timedelta(days=7):flags.add('VIX_HISTORY_PARTIAL')
    shared_flags=set(flags);shared_refs=dict(refs);output=[]
    for s in names:
        if s not in current:continue
        flags=set(shared_flags);refs=dict(shared_refs);stock=current[s];sector=sector_map.get(s)
        rs_open=rs_five=None
        if sector in current:
            reference(current[sector],'BAR');reference(first[sector],'BAR')
            rs_open=relative_strength(float(stock['close']),float(first[s]['open']),float(current[sector]['close']),float(first[sector]['open']))
            common=sorted(set(daily[s])&set(daily[sector]))
            past=[d for d in common if d<day]
            if len(past)>=5:
                base=past[-5];sb=daily[s][base][-1];ib=daily[sector][base][-1]
                reference(sb,'BAR');reference(ib,'BAR')
                rs_five=relative_strength(float(stock['close']),float(sb['close']),float(current[sector]['close']),float(ib['close']))
            else:flags.add('RS_5D_HISTORY_MISSING')
        else:flags.add('SECTOR_CONTEXT_MISSING')
        past=sorted(d for d in daily[s] if d<day)[-20:]
        value=spread=None
        complete_days=all(
            {r['bar_start'].astimezone(IST).hour*60+r['bar_start'].astimezone(IST).minute for r in daily[s][d]}
            >= set(range(9*60+15,15*60+30)) and not any('GAP' in r['flags'] for r in daily[s][d]) for d in past)
        if len(past)==20 and all(d in spreads[s] for d in past) and complete_days:
            values=[];daily_spreads=[]
            for d in past:
                rows=daily[s][d]
                for r in rows:reference(r,'LIQUIDITY_BAR')
                values.append(sum(float((r['high']+r['low']+r['close'])/3)*r['volume'] for r in rows))
                daily_spreads.append(median(value for value,_ in spreads[s][d]))
                for _,quote in spreads[s][d]:reference(quote,'SPREAD')
            value=median(values);spread=median(daily_spreads);flags.add('LIQUIDITY_VALUE_APPROXIMATE')
        else:
            flags.add('LIQUIDITY_20D_HISTORY_MISSING')
            if len(past)==20 and not complete_days:flags.add('LIQUIDITY_INCOMPLETE_SESSIONS')
        event_flags=[]
        for r in raw_events:
            if r['symbol'] not in {s,'*','MARKET'}:continue
            event=r['event_type'].lower()
            occurred=aware(r['occurred_at'])
            if (event in {'results_day','expiry_day','budget_day'} and occurred.astimezone(IST).date()==day) or (event in {'announcement','recent_announcement'} and at-timedelta(minutes=60)<=occurred<=at):
                event_flags.append('recent_announcement' if event=='announcement' else event);reference(r,'EVENT')
        method='APPROXIMATE' if any(r['method']=='APPROXIMATE' for r in eligible if r['symbol'] in {s,sector}) else 'ESTIMATE'
        output.append(dict(symbol=s,instrument_key=stock['instrument_key'],session_date=day,minute=at,index_regime=regime,vix_regime=volatility,sector_rs_open=rs_open,sector_rs_5d=rs_five,breadth_above_vwap_fraction=fraction,advancers=advancers,decliners=decliners,time_of_day=category,liquidity_tier=liquidity_tier(value,spread,value_thresholds=value_thresholds,spread_thresholds=spread_thresholds),event_flags=sorted(set(event_flags)),source='CONTEXT',method=method,confidence='LOW',flags=sorted(flags),available_at=at,inputs=sorted(refs.values(),key=lambda r:(r['available_at'],r['record_id']))))
    return pa.Table.from_pylist(output,schema=CONTEXT_SCHEMA)
