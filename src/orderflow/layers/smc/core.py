"""Section 4.4 SMC, with explicitly supplied unresolved source policies.

All detections use closed, available bars. Lifecycle records are point-in-time
versions, never retroactively visible before their confirming bars close.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal as D
import pyarrow as pa
from orderflow.auth.core import aware
from orderflow.schema import BAR_SCHEMA, LEVEL_SCHEMA, EVENT_SCHEMA


def atr_values(rows: list[dict], *, period: int = 14, smoothing: str) -> list[D | None]:
    """ATR from max(high-low, abs(high-prev_close), abs(low-prev_close)).

    Source does not specify smoothing; require SMA or Wilder explicitly. Wilder
    is initialized with the arithmetic mean of the first period true ranges.
    """
    if period < 1 or smoothing not in ('sma', 'wilder'):
        raise ValueError('positive ATR period and explicit sma/wilder smoothing required')
    true_ranges=[]; result=[]; previous=None; estimate=None
    for row in rows:
        tr=row['high']-row['low']
        if previous is not None: tr=max(tr,abs(row['high']-previous),abs(row['low']-previous))
        true_ranges.append(tr); previous=row['close']
        if len(true_ranges)<period: result.append(None); continue
        if smoothing=='sma' or estimate is None: estimate=sum(true_ranges[-period:])/period
        else: estimate=(estimate*(period-1)+tr)/period
        result.append(estimate)
    return result


def _closed(data: pa.Table, as_of: datetime) -> list[dict]:
    if not data.schema.equals(BAR_SCHEMA): raise ValueError('BAR_SCHEMA required')
    cutoff=aware(as_of)
    rows=[r for r in data.to_pylist() if r['available_at']<=cutoff and r['bar_end']<=cutoff]
    return sorted(rows,key=lambda r:(r['bar_end'],r['available_at'],r['bar_id']))


def _confirmed(rows: list[dict], center: int, n: int, policy: str) -> list[dict]:
    result=[]; candidate=rows[center]; neighbors=rows[center-n:center]+rows[center+1:center+n+1]
    for side,column in [('HIGH','high'),('LOW','low')]:
        p=candidate[column]
        if side=='HIGH': qualifies=all(p>r[column] if policy=='strict' else p>=r[column] for r in neighbors)
        else: qualifies=all(p<r[column] if policy=='strict' else p<=r[column] for r in neighbors)
        if qualifies:
            result.append(dict(side=side,price=p,origin_at=candidate['bar_end'],available_at=max(r['available_at'] for r in rows[center-n:center+n+1]),bar_id=candidate['bar_id'],confirm_index=center+n,inputs=[dict(record_id=r['bar_id'],available_at=r['available_at']) for r in rows[center-n:center+n+1]]))
    return result


def fractals(data: pa.Table, *, as_of: datetime, bars_each_side: int = 2, tie_policy: str) -> list[dict]:
    """Section 4.4 fractals: N bars each side, available after right N close.

    Equal-swing tie behavior is unspecified in source; require strict or inclusive.
    """
    if bars_each_side<1 or tie_policy not in ('strict','inclusive'): raise ValueError('explicit swing tie policy and positive N required')
    grouped=defaultdict(list)
    for row in _closed(data,as_of): grouped[(row['instrument_key'],row['timeframe_minutes'])].append(row)
    result=[]
    for rows in grouped.values():
        for center in range(bars_each_side,len(rows)-bars_each_side):
            for swing in _confirmed(rows,center,bars_each_side,tie_policy):
                result.append({**swing,'symbol':rows[center]['symbol'],'instrument_key':rows[center]['instrument_key'],'timeframe_minutes':rows[center]['timeframe_minutes']})
    return result


def displacement(row: dict, atr: D | None, *, range_multiple: D = D('1.5'), body_fraction: D = D('.6')) -> bool:
    """Section 4.4: range >= 1.5 ATR(14), body >= 60% of range."""
    span=row['high']-row['low']
    return atr is not None and atr>0 and span>0 and span>=range_multiple*atr and abs(row['close']-row['open'])>=body_fraction*span


def dealing_range(low: D, high: D, price: D, *, side: str, midpoint_fraction: D = D('.5'), ote_fractions: tuple[D,D] = (D('.62'),D('.79'))) -> dict:
    """Last confirmed low-to-high midpoint; OTE is 62–79% retracement."""
    if high<=low or side not in ('BUY','SELL'): raise ValueError('positive dealing range and BUY/SELL required')
    span=high-low
    lower,upper=ote_fractions
    if not 0<=lower<upper<=1 or not 0<midpoint_fraction<1: raise ValueError('invalid dealing range fractions')
    bounds=(high-upper*span,high-lower*span) if side=='BUY' else (low+lower*span,low+upper*span)
    midpoint=low+midpoint_fraction*span
    return dict(low=low,high=high,midpoint=midpoint,position='PREMIUM' if price>midpoint else 'DISCOUNT' if price<midpoint else 'MIDPOINT',ote_low=bounds[0],ote_high=bounds[1])


def timeframe_bias(direction_60m: str | None, direction_15m: str | None, *, side: str) -> str:
    """Section 4.4: 60m/15m structure aligned or opposed to candidate side."""
    if side not in ('BUY','SELL'): raise ValueError('BUY/SELL candidate side required')
    if direction_60m==direction_15m==side: return 'ALIGNED'
    opposite='SELL' if side=='BUY' else 'BUY'
    if direction_60m==direction_15m==opposite: return 'OPPOSED'
    return 'MIXED'


def smc(data: pa.Table, *, as_of: datetime, tick_size: D, atr_smoothing: str,
        swing_tie_policy: str, fvg_comparator: str, bars_each_side: int = 2,
        atr_period: int = 14, break_basis: str = 'close', order_block_bounds: str = 'low_high',
        min_fvg_ticks: int = 2, min_fvg_atr: D = D('.1'),
        pool_tolerance_atr: D = D('.1'), pool_min_swings: int = 2, sweep_bars: int = 3,
        sweep_penetration_ticks: int = 1, displacement_range_multiple: D = D('1.5'),
        displacement_body_fraction: D = D('.6'),
        external_pools: pa.Table | None = None) -> tuple[pa.Table,pa.Table]:
    """Section 4.4 closed-bar structures as canonical LEVEL/EVENT contracts.

    FVG comparator must explicitly be 'eq' (printed source) or 'ge' (unconfirmed
    intended minimum). Neither is selected implicitly. ATR and swing ties also
    require caller policy. Input bars may span symbols, sessions and timeframes;
    structure continues across sessions within each symbol/timeframe. Event IDs
    are instrument_key:timeframe_minutes:event_type:bar_id:side:price, allowing
    explicit timeframe filtering without adding fields to EVENT_SCHEMA. Prior
    day/week and IB pools come from the canonical external LEVEL table; session
    extrema and equal-swing pools are generated here.
    """
    if fvg_comparator not in ('eq','ge'): raise ValueError('explicit FVG comparator eq/ge required; source unresolved')
    if atr_smoothing not in ('sma','wilder') or swing_tie_policy not in ('strict','inclusive'): raise ValueError('explicit ATR smoothing and swing tie policy required')
    if tick_size<=0 or pool_min_swings<2 or sweep_penetration_ticks<1 or sweep_bars<1 or bars_each_side<1 or break_basis not in ('close','wick') or order_block_bounds not in ('low_high','low_open'): raise ValueError('invalid SMC parameters')
    cutoff=aware(as_of); groups=defaultdict(list)
    for row in _closed(data,cutoff):
        if row['bar_kind']!='TIME': raise ValueError('SMC requires time bars')
        groups[(row['instrument_key'],row['timeframe_minutes'])].append(row)
    external=[]
    if external_pools is not None:
        if not external_pools.schema.equals(LEVEL_SCHEMA): raise ValueError('external pools require LEVEL_SCHEMA')
        external=[r for r in external_pools.to_pylist() if r['available_at']<=cutoff]
    levels=[]; events=[]
    for (key,tf),rows in groups.items():
        atrs=atr_values(rows,period=atr_period,smoothing=atr_smoothing)
        input_flags={r['bar_id']:r['flags'] for r in rows}
        input_flags.update({r['record_id']:r['flags'] for r in external})
        input_provenance={r['bar_id']:(r['method'],r['confidence']) for r in rows}
        input_provenance.update({r['record_id']:(r['method'],r['confidence']) for r in external})
        highs=[]; lows=[]; trend=None; broken=set(); active=[]; pools=[]; pending={}; swept=set(); session_extremes={}; session=None
        for r in external:
            if r['instrument_key']==key and (r['timeframe_minutes'] in (None,tf)): pools.append(r.copy())
        def provenance(bar,refs):
            dependencies=[(bar['method'],bar['confidence'])]+[input_provenance[ref['record_id']] for ref in refs if ref['record_id'] in input_provenance]
            methods={item[0] for item in dependencies}
            method='APPROXIMATE' if 'APPROXIMATE' in methods else 'ESTIMATE' if 'ESTIMATE' in methods else 'BAR_STRUCTURE'
            confidence_rank={'UNKNOWN':0,'LOW':1,'MEDIUM':2,'HIGH':3}
            confidence=min((item[1] for item in dependencies),key=lambda value:confidence_rank.get(value,0))
            return dict(symbol=bar['symbol'],instrument_key=key,session_date=bar['session_date'],source=bar['source'],method=method,confidence=confidence,flags=sorted(set(bar['flags']).union(*(input_flags.get(ref['record_id'],[]) for ref in refs))),available_at=max([bar['available_at']]+[ref['available_at'] for ref in refs]),inputs=refs)
        def level(kind,bar,low,high,side,origin,refs,identifier=None):
            item=dict(**provenance(bar,refs),record_id=identifier or f'{key}:{tf}:{kind}:{bar["bar_id"]}:{side}',type=kind,timeframe_minutes=tf,low=low,high=high,side=side,origin_at=origin,created_at=bar['bar_end'],invalidated_at=None,mitigated_at=None,state='ACTIVE')
            levels.append(item); active.append(item)
            input_provenance[item['record_id']]=(item['method'],item['confidence'])
            input_flags[item['record_id']]=item['flags']
            return item
        def event(kind,bar,price,side,refs,origin=None):
            events.append(dict(**provenance(bar,refs),event_id=f'{key}:{tf}:{kind}:{bar["bar_id"]}:{side}:{price}',event_type=kind,occurred_at=origin or bar['bar_end'],confirmed_at=bar['bar_end'],price=price,side=side,strength=None,zone_id=None))
        for i,bar in enumerate(rows):
            ref=dict(record_id=bar['bar_id'],available_at=bar['available_at']); atr=atrs[i]
            atr_start=0 if atr_smoothing=='wilder' else max(0,i-atr_period)
            atr_refs=[dict(record_id=r['bar_id'],available_at=r['available_at']) for r in rows[atr_start:i+1]]
            # A lifecycle state is observable only after this closed bar.
            for item in active:
                if item['type'] not in ('ORDER_BLOCK','FVG') or item['state'] in ('INVALIDATED','FILLED') or item['created_at']>=bar['bar_end']: continue
                crossed=bar['close']<item['low'] if item['side']=='BUY' else bar['close']>item['high']
                touched=bar['low']<=item['high'] and bar['high']>=item['low']
                if crossed or touched:
                    item['available_at']=max(item['available_at'],bar['available_at']); item['inputs'].append(ref.copy())
                    changed=provenance(bar,item['inputs'])
                    item['method']=changed['method']; item['confidence']=changed['confidence']; item['flags']=changed['flags']
                    input_provenance[item['record_id']]=(item['method'],item['confidence'])
                    if touched and item['mitigated_at'] is None: item['mitigated_at']=bar['bar_end']
                    if crossed: item['state']='FILLED' if item['type']=='FVG' else 'INVALIDATED'; item['invalidated_at']=bar['bar_end']
                    elif touched: item['state']='PARTIAL_FILL' if item['type']=='FVG' else 'MITIGATED'
            # Confirm only after both right-side bars close.
            if i>=2*bars_each_side:
                for swing in _confirmed(rows,i-bars_each_side,bars_each_side,swing_tie_policy):
                    history=highs if swing['side']=='HIGH' else lows
                    kind='SWING_HIGH' if swing['side']=='HIGH' else 'SWING_LOW'; side='SELL' if swing['side']=='HIGH' else 'BUY'
                    level(kind,bar,swing['price'],swing['price'],side,swing['origin_at'],swing['inputs'])
                    if atr is not None:
                        matches=[s for s in history if abs(s['price']-swing['price'])<=pool_tolerance_atr*atr]
                        if len(matches)+1>=pool_min_swings:
                            refs=[ref for matched in matches for ref in matched['inputs']]+swing['inputs']+atr_refs
                            pool=level('EQUAL_HIGH' if side=='SELL' else 'EQUAL_LOW',bar,min([swing['price']]+[m['price'] for m in matches]),max([swing['price']]+[m['price'] for m in matches]),side,matches[-1]['origin_at'],refs)
                            pools.append(pool)
                    history.append(swing)
                if len(highs)>=2 and len(lows)>=2 and (trend is None or _confirmed(rows,i-bars_each_side,bars_each_side,swing_tie_policy)):
                    if highs[-1]['price']>highs[-2]['price'] and lows[-1]['price']>lows[-2]['price']: trend='BUY'
                    elif highs[-1]['price']<highs[-2]['price'] and lows[-1]['price']<lows[-2]['price']: trend='SELL'
            # Sweeps consult pools that existed before the current bar.
            for pool in pools:
                pid=pool['record_id']
                if pool['available_at']>=bar['bar_end'] or pid in swept or pool['invalidated_at'] is not None: continue
                high_side=pool['side']=='SELL'; price=pool['high'] if high_side else pool['low']
                penetrated=bar['high']>=price+sweep_penetration_ticks*tick_size if high_side else bar['low']<=price-sweep_penetration_ticks*tick_size
                if pid not in pending and penetrated: pending[pid]=dict(start=i,origin=bar['bar_end'],refs=[dict(record_id=pid,available_at=pool['available_at'])],beyond=0)
                if pid not in pending: continue
                p=pending[pid]; p['refs'].append(ref.copy())
                inside=bar['close']<price if high_side else bar['close']>price
                beyond=bar['close']>price if high_side else bar['close']<price
                p['beyond']=p['beyond']+1 if beyond else 0
                if inside and i-p['start']<sweep_bars:
                    event('SWEEP_REVERSAL',bar,price,'SELL' if high_side else 'BUY',p['refs'],p['origin']); swept.add(pid)
                elif p['beyond']>=sweep_bars:
                    event('SWEEP_CONTINUATION',bar,price,'BUY' if high_side else 'SELL',p['refs'],p['origin']); swept.add(pid)
                elif i-p['start']>=sweep_bars: swept.add(pid)
            is_displacement=displacement(bar,atr,range_multiple=displacement_range_multiple,body_fraction=displacement_body_fraction)
            if is_displacement: event('DISPLACEMENT',bar,bar['close'],'BUY' if bar['close']>bar['open'] else 'SELL',atr_refs)
            for direction,history,column in [('BUY',highs,'high'),('SELL',lows,'low')]:
                if not history or trend is None: continue
                swing=history[-1]; identity=(direction,swing['bar_id'])
                value=bar['close'] if break_basis=='close' else bar[column]
                beyond=value>swing['price'] if direction=='BUY' else value<swing['price']
                if not beyond or identity in broken or swing['available_at']>=bar['bar_end']: continue
                kind='BOS' if direction==trend else 'CHOCH'
                event(kind,bar,swing['price'],direction,[*swing['inputs'],ref]); broken.add(identity)
                if kind=='CHOCH': trend=direction; continue
                displacement_indices=[j for j in range(i,-1,-1) if displacement(rows[j],atrs[j],range_multiple=displacement_range_multiple,body_fraction=displacement_body_fraction) and (rows[j]['close']>rows[j]['open'])==(direction=='BUY')]
                if displacement_indices:
                    leg=displacement_indices[0]
                    candidates=[j for j in range(leg-1,-1,-1) if (rows[j]['close']<rows[j]['open'] if direction=='BUY' else rows[j]['close']>rows[j]['open'])]
                    if candidates:
                        j=candidates[0]; origin=rows[j]
                        lo=origin['low'] if direction=='BUY' or order_block_bounds=='low_high' else origin['open']
                        hi=origin['high'] if direction=='SELL' or order_block_bounds=='low_high' else origin['open']
                        refs=[dict(record_id=r['bar_id'],available_at=r['available_at']) for r in rows[(0 if atr_smoothing=='wilder' else min(j,max(0,leg-atr_period))):i+1]]
                        level('ORDER_BLOCK',bar,lo,hi,direction,origin['bar_end'],refs)
            if i>=2 and atr is not None:
                first=rows[i-2]
                for direction,lo,hi in [('BUY',first['high'],bar['low']),('SELL',bar['high'],first['low'])]:
                    gap=hi-lo; threshold=min_fvg_atr*atr
                    qualifies=gap>=threshold if fvg_comparator=='ge' else gap==threshold
                    if gap>=min_fvg_ticks*tick_size and qualifies:
                        refs=[dict(record_id=r['bar_id'],available_at=r['available_at']) for r in rows[min(i-2,atr_start):i+1]]
                        level('FVG',bar,lo,hi,direction,first['bar_end'],refs)
            if session!=bar['session_date']:
                for old in session_extremes.values():
                    old['state']='EXPIRED'; old['invalidated_at']=bar['bar_end']
                    old['available_at']=max(old['available_at'],bar['available_at']); old['inputs'].append(ref.copy())
                    changed=provenance(bar,old['inputs'])
                    old['method']=changed['method']; old['confidence']=changed['confidence']; old['flags']=changed['flags']
                    input_provenance[old['record_id']]=(old['method'],old['confidence'])
                session_extremes={}; session=bar['session_date']
            for kind,column,side in [('SESSION_HIGH','high','SELL'),('SESSION_LOW','low','BUY')]:
                old=session_extremes.get(kind)
                improves=old is None or (bar[column]>old['high'] if side=='SELL' else bar[column]<old['low'])
                if improves:
                    if old is not None:
                        old['state']='SUPERSEDED'; old['invalidated_at']=bar['bar_end']
                        old['available_at']=max(old['available_at'],bar['available_at']); old['inputs'].append(ref.copy())
                        changed=provenance(bar,old['inputs'])
                        old['method']=changed['method']; old['confidence']=changed['confidence']; old['flags']=changed['flags']
                        input_provenance[old['record_id']]=(old['method'],old['confidence'])
                    pool=level(kind,bar,bar[column],bar[column],side,bar['bar_end'],[ref.copy()])
                    session_extremes[kind]=pool; pools.append(pool)
    return pa.Table.from_pylist(levels,schema=LEVEL_SCHEMA),pa.Table.from_pylist(events,schema=EVENT_SCHEMA)
