"""BOOTSTRAP 4.3: volume-weighted population bands and confirmed anchors."""
from datetime import datetime,timedelta,time
from decimal import Decimal
from math import sqrt
from zoneinfo import ZoneInfo
from typing import Any,Iterable
import pyarrow as pa
from orderflow.auth.core import aware
from orderflow.trades.core import _session_bounds
from orderflow.schema import TRADE_SCHEMA,CANDLE_SCHEMA,FEATURE_SCHEMA


def weighted_vwap(samples:Iterable[tuple[Decimal,int]]) -> dict[str,float|None]:
    """sum(p*v)/sum(v); sigma=sqrt(sum(v*(p-VWAP)^2)/sum(v))."""
    weight=0;mean=0.;moment=0.
    for price,volume in samples:
        if volume<0:raise ValueError('negative volume')
        if not volume:continue
        total=weight+volume;delta=float(price)-mean
        mean+=delta*volume/total;moment+=volume*delta*(float(price)-mean);weight=total
    return {'vwap':mean if weight else None,'sigma':sqrt(max(0.,moment/weight)) if weight else None}


def vwap_features(data:pa.Table,*,as_of:datetime,anchors:list[dict[str,Any]]|None=None,
                  bands:tuple[int,...]=(1,2,3),session_open:time=time(9,15),
                  session_close:time=time(15,30)) -> pa.Table:
    """Session/week/month and supplied confirmed-anchor VWAP at as_of.

    Caller supplies gap, prior-day high/low, swing and event origins with actual
    confirmation availability. Only regular-session inputs contribute. History uses HLC3 and is APPROXIMATE; snapshot
    volume is ESTIMATE. Every source and anchor must be available by as_of.
    """
    cutoff=aware(as_of);history=data.schema.equals(CANDLE_SCHEMA)
    if not history and not data.schema.equals(TRADE_SCHEMA):raise ValueError('canonical trade/candle schema required')
    local=cutoff.astimezone(ZoneInfo('Asia/Kolkata'));day=local.date()
    origins={'SESSION':day,'WEEK':day-timedelta(days=day.weekday()),'MONTH':day.replace(day=1)}
    groups={};bounds={}
    for batch in data.to_batches(max_chunksize=10000):
        for row in batch.to_pylist():
            if row['available_at']>cutoff or {'DUPLICATE','OUT_OF_ORDER','OUTSIDE_SESSION'}&set(row['flags']):continue
            if history and row['bar_end']>cutoff:continue
            source_day=row['session_date']
            if source_day not in bounds:bounds[source_day]=_session_bounds(source_day,session_open,session_close)
            opening,closing=bounds[source_day]
            if history:
                if row['bar_start']<opening or row['bar_end']>closing:continue
            elif not opening<=(row['exchange_ts'] or row['receipt_ts'])<closing:continue
            price=(row['high']+row['low']+row['close'])/3 if history else row['price']
            timestamp=row['bar_start'] if history else row['exchange_ts'] or row['receipt_ts']
            if timestamp>cutoff:continue
            key=(row['symbol'],row['instrument_key'])
            group=groups.setdefault(key,{})
            scopes=[(name, timestamp.astimezone(ZoneInfo('Asia/Kolkata')).date()>=origin and row['session_date']<=day,None)
                    for name,origin in origins.items()]
            for anchor in anchors or []:
                confirmation=aware(anchor['available_at']);origin=aware(anchor['origin_at'])
                if confirmation<origin:raise ValueError('anchor confirmation precedes origin')
                valid=confirmation<=cutoff and timestamp>=origin and anchor.get('instrument_key',row['instrument_key'])==row['instrument_key']
                scopes.append(('ANCHOR_'+anchor['id'],valid,anchor))
            for name,valid,anchor in scopes:
                if not valid:continue
                state=group.setdefault(name,dict(weight=0,mean=0.,moment=0.,inputs=[],start=timestamp,anchor=anchor))
                volume=row['volume']
                if volume<0:raise ValueError('negative volume')
                if volume:
                    total=state['weight']+volume;delta=float(price)-state['mean']
                    state['mean']+=delta*volume/total
                    state['moment']+=volume*delta*(float(price)-state['mean']);state['weight']=total
                state['inputs'].append(dict(record_id=f"{row['instrument_key']}:{timestamp.isoformat()}",available_at=row['available_at']))
                state['start']=min(state['start'],timestamp)
    output=[]
    for (symbol,key),states in sorted(groups.items()):
        for name,state in sorted(states.items()):
            mean=state['mean'] if state['weight'] else None
            sigma=sqrt(max(0.,state['moment']/state['weight'])) if state['weight'] else None
            inputs=state['inputs']
            if state['anchor']:inputs=inputs+[dict(record_id='anchor:'+state['anchor']['id'],available_at=state['anchor']['available_at'])]
            values={name+'_VWAP':mean,name+'_SIGMA':sigma}
            for band in bands:
                if band<=0:raise ValueError('positive sigma multiple required')
                values[name+f'_BAND_UP_{band}']=mean+band*sigma if mean is not None else None
                values[name+f'_BAND_DOWN_{band}']=mean-band*sigma if mean is not None else None
            for feature,value in values.items():
                output.append(dict(symbol=symbol,instrument_key=key,session_date=day,minute=cutoff,name=feature,
                    level=None,value=value,r_squared=None,n=len(state['inputs']),unknown_share=None,
                    window_start=state['start'],window_end=cutoff,source='history' if history else 'feed',
                    method='APPROXIMATE' if history else 'ESTIMATE',confidence='LOW',
                    flags=[] if mean is not None else ['ZERO_VOLUME'],available_at=cutoff,inputs=inputs))
    return pa.Table.from_pylist(output,schema=FEATURE_SCHEMA)


def vwap_events(rows:list[dict[str,Any]],*,as_of:datetime) -> list[dict[str,Any]]:
    """Reclaim after two below closes; rejection touch; +/-2,3 tags and 3-close acceptance.

    Rows are closed bars joined to contemporaneously available VWAP/sigma. An
    optional vwap_available_at further gates the joined value's availability.
    """
    cutoff=aware(as_of);events=[];below=0;counts={}
    for row in sorted(rows,key=lambda r:r['available_at']):
        available=max(aware(row['available_at']),aware(row.get('vwap_available_at',row['available_at'])))
        if available>cutoff:continue
        vwap=row['vwap'];sigma=row['sigma']
        if vwap is None or sigma is None:below=0;counts={};continue
        close,low,high=map(float,(row['close'],row['low'],row['high']))
        base=dict(available_at=available)
        if close>vwap and below>=2:events.append(dict(base,type='VWAP_RECLAIM',side='BUY'))
        below=below+1 if close<vwap else 0
        if low<=vwap<=high and close!=vwap:
            events.append(dict(base,type='VWAP_REJECTION',side='BUY' if close>vwap else 'SELL'))
        for multiple in (2,3):
            for side,level,beyond in [('BUY',vwap+multiple*sigma,close>vwap+multiple*sigma),
                                     ('SELL',vwap-multiple*sigma,close<vwap-multiple*sigma)]:
                if sigma>0 and low<=level<=high:events.append(dict(base,type='BAND_TAG',side=side,sigma_multiple=multiple))
                key=(side,multiple);counts[key]=counts.get(key,0)+1 if beyond and sigma>0 else 0
                if counts[key]==3:events.append(dict(base,type='BAND_ACCEPTANCE',side=side,sigma_multiple=multiple))
    return events


def vwap_event_table(bars:pa.Table,features:pa.Table,*,as_of:datetime) -> pa.Table:
    """BOOTSTRAP 4.3 events from canonical closed bars and session VWAP/sigma.

    Join the latest same-session snapshot minute <= bar end at the first time
    both snapshot fields and the closed bar are available. That first eligible
    join is immutable: later revisions never revise earlier emitted events.
    Prior confirming bars and all VWAP dependencies contribute availability.
    Arrival order governs state; stale/duplicate bars cannot confirm a sequence
    and carry quality flags on any single-bar tag/rejection they produce.
    """
    from math import isfinite
    from orderflow.schema import BAR_SCHEMA,EVENT_SCHEMA
    cutoff=aware(as_of)
    if not bars.schema.equals(BAR_SCHEMA) or not features.schema.equals(FEATURE_SCHEMA):
        raise ValueError('canonical BAR and FEATURE contracts required')

    def availability(record:dict[str,Any],*,bar:bool=False) -> datetime:
        times=[aware(record['available_at'])]+[aware(ref['available_at']) for ref in record['inputs']]
        times.append(aware(record['bar_end'] if bar else record['minute']))
        return max(times)

    # Preserve the first published version of each snapshot field.
    indexed={}
    for feature in features.to_pylist():
        if feature['name'] not in {'SESSION_VWAP','SESSION_SIGMA'}:continue
        available=availability(feature)
        if available>cutoff:continue
        key=(feature['instrument_key'],feature['session_date'])
        version_key=(feature['minute'],feature['name'])
        group=indexed.setdefault(key,{})
        candidate=dict(feature,_effective=available)
        old=group.get(version_key)
        if old is None or (available,str(feature['value']))<(old['_effective'],str(old['value'])):
            group[version_key]=candidate
    snapshots={}
    for key,fields in indexed.items():
        snapshots[key]=[]
        for minute in sorted({version_key[0] for version_key in fields}):
            mean=fields.get((minute,'SESSION_VWAP'));sigma=fields.get((minute,'SESSION_SIGMA'))
            if mean and sigma:
                snapshots[key].append((minute,max(mean['_effective'],sigma['_effective']),mean,sigma))
    joined=[]
    for bar in bars.to_pylist():
        if 'OUTSIDE_SESSION' in bar['flags']:continue
        ready=availability(bar,bar=True)
        if ready>cutoff:continue
        candidates=[(max(ready,published),minute,mean,sigma) for minute,published,mean,sigma in
                    snapshots.get((bar['instrument_key'],bar['session_date']),[]) if minute<=bar['bar_end']]
        if not candidates:continue
        first=min(candidate[0] for candidate in candidates)
        _,minute,mean,sigma=max((c for c in candidates if c[0]==first),key=lambda c:c[1])
        flags=set(bar['flags'])|set(mean['flags'])|set(sigma['flags'])
        if first>ready:flags.add('LATE_VWAP')
        if ready>bar['available_at'] or mean['_effective']>mean['available_at'] or sigma['_effective']>sigma['available_at']:
            flags.add('SOURCE_AVAILABLE_AFTER_RECORD')
        joined.append(dict(bar=bar,mean=mean,sigma=sigma,ready=first,flags=flags))
    joined.sort(key=lambda j:(j['ready'],j['bar']['bar_end'],j['bar']['instrument_key'],j['bar']['bar_id']))
    states={};events=[]

    def emit(kind:str,side:str,price:Decimal,origin:dict,sources:list[dict],multiple:int|None=None) -> None:
        bar=origin['bar'];references={};flags=set();methods=[]
        for source in sources:
            srcbar=source['bar'];flags.update(source['flags']);methods.extend((srcbar['method'],source['mean']['method'],source['sigma']['method']))
            references[(srcbar['bar_id'],srcbar['available_at'])]=dict(record_id=srcbar['bar_id'],available_at=srcbar['available_at'])
            for feature in (source['mean'],source['sigma']):
                identity=f"{feature['instrument_key']}:{feature['minute'].isoformat()}:{feature['name']}"
                references[(identity,feature['_effective'])]=dict(record_id=identity,available_at=feature['_effective'])
                for ref in feature['inputs']+srcbar['inputs']:
                    references[(ref['record_id'],ref['available_at'])]=ref
        confirmed=max(source['bar']['bar_end'] for source in sources)
        available=max([confirmed]+[source['ready'] for source in sources]+[ref['available_at'] for ref in references.values()])
        events.append(dict(symbol=bar['symbol'],instrument_key=bar['instrument_key'],session_date=bar['session_date'],
            event_id=f"{bar['bar_id']}:{kind}:{side}:{multiple or 0}",event_type=kind,occurred_at=bar['bar_end'],
            confirmed_at=confirmed,price=price.quantize(Decimal('.00000001')),side=side,strength=None,zone_id=None,
            source=bar['source'],method='APPROXIMATE' if 'APPROXIMATE' in methods else 'ESTIMATE',confidence='LOW',
            flags=sorted(flags),available_at=available,inputs=list(references.values())))

    for row in joined:
        bar=row['bar'];key=(bar['instrument_key'],bar['session_date'],bar['bar_kind'],bar['timeframe_minutes'],bar['volume_target'])
        state=states.setdefault(key,dict(below=[],bands={},last_end=None,pending_flags=set()))
        sequential=True
        if state['last_end'] is not None:
            if bar['bar_end']<=state['last_end']:
                row['flags'].add('DUPLICATE' if bar['bar_end']==state['last_end'] else 'OUT_OF_ORDER');sequential=False
            elif bar['bar_start']!=state['last_end']:
                row['flags'].add('GAP');state['below']=[];state['bands']={}
        if {'DUPLICATE','OUT_OF_ORDER','OUTSIDE_SESSION'}&row['flags']:sequential=False
        if not sequential or 'GAP' in row['flags']:state['below']=[];state['bands']={}
        state['last_end']=max(state['last_end'],bar['bar_end']) if state['last_end'] else bar['bar_end']
        row['flags'].update(state['pending_flags'])
        mean=row['mean']['value'];sigma=row['sigma']['value']
        if mean is None or sigma is None or not isfinite(mean) or not isfinite(sigma) or sigma<0 or any(bar[name] is None for name in ('close','high','low')):
            state['below']=[];state['bands']={};state['pending_flags'].update(row['flags']|{'MISSING_VWAP_INPUT'})
            continue
        state['pending_flags']=set()
        close,low,high=map(float,(bar['close'],bar['low'],bar['high']))
        if sequential and close>mean and len(state['below'])>=2:
            emit('VWAP_RECLAIM','BUY',bar['close'],row,state['below']+[row])
        state['below']=state['below']+[row] if sequential and close<mean else []
        if low<=mean<=high and close!=mean:
            emit('VWAP_REJECTION','BUY' if close>mean else 'SELL',bar['close'],row,[row])
        for multiple in (2,3):
            for side,level,beyond in [('BUY',mean+multiple*sigma,close>mean+multiple*sigma),('SELL',mean-multiple*sigma,close<mean-multiple*sigma)]:
                if sigma>0 and low<=level<=high:
                    emit('BAND_TAG',side,Decimal(str(level)),row,[row],multiple)
                band=(side,multiple)
                previous=state['bands'].get(band,[])
                current=previous+[row] if sequential and beyond and sigma>0 else []
                state['bands'][band]=current
                if len(current)==3:
                    emit('BAND_ACCEPTANCE',side,Decimal(str(level)),row,current,multiple)
    events.sort(key=lambda e:(e['available_at'],e['event_id']))
    return pa.Table.from_pylist(events,schema=EVENT_SCHEMA)
