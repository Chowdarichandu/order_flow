"""BOOTSTRAP 4.1: footprint, diagonal and stacked imbalance."""
from decimal import Decimal
from typing import Any
from bisect import bisect_left
import numpy as np
import pyarrow as pa
from orderflow.schema import TRADE_SCHEMA,BAR_SCHEMA,FOOTPRINT_SCHEMA


def diagonal(levels:dict[Decimal,dict[str,int]],*,tick_size:Decimal,ratio:float,
             min_volume:float) -> tuple[set[Decimal],set[Decimal]]:
    """Buy ask(p)>=R*bid(p-tick) and >=min; sell bid(p)>=R*ask(p+tick) and >=min."""
    if tick_size<=0 or ratio<=0 or min_volume<0:
        raise ValueError('invalid diagonal parameters')
    buys,sells=set(),set()
    for price,volume in levels.items():
        if volume['ask']>=ratio*levels.get(price-tick_size,{}).get('bid',0) and volume['ask']>=min_volume:
            buys.add(price)
        if volume['bid']>=ratio*levels.get(price+tick_size,{}).get('ask',0) and volume['bid']>=min_volume:
            sells.add(price)
    return buys,sells


def stacked(prices:set[Decimal],*,tick_size:Decimal,count:int=3) -> set[Decimal]:
    """At least count consecutive tick-spaced same-side imbalance levels."""
    if count<1 or tick_size<=0:raise ValueError('invalid stack parameters')
    result=set();run=[]
    for price in sorted(prices):
        if run and price-run[-1]!=tick_size:
            if len(run)>=count:result.update(run)
            run=[]
        run.append(price)
    if len(run)>=count:result.update(run)
    return result


def footprint(trades:pa.Table,bars:pa.Table,*,tick_size:Decimal,ratio:float=3,
              percentile:float=20,stacked_levels:int=3) -> pa.Table:
    """Per bar/tick price: bid=SELL, ask=BUY; UNKNOWN separate and ESTIMATE.

    Threshold is the percentile of cumulative per-price symbol-day volume
    available so far, including current closed bar; no later levels contribute.
    Input prices must already align to instrument tick size, never rounded.
    """
    if not trades.schema.equals(TRADE_SCHEMA) or not bars.schema.equals(BAR_SCHEMA):
        raise ValueError('canonical trade/bar contracts required')
    if tick_size<=0 or not 0<=percentile<=100:raise ValueError('invalid footprint parameters')
    indexed={}
    for row in trades.to_pylist():
        if {'DUPLICATE','OUT_OF_ORDER'}&set(row['flags']):continue
        indexed.setdefault((row['instrument_key'],row['session_date']),[]).append(row)
    for key,rows in indexed.items():
        rows.sort(key=lambda row:(row['exchange_ts'] or row['receipt_ts'],row['sequence']))
        indexed[key]=([row['exchange_ts'] or row['receipt_ts'] for row in rows],rows)
    available_rows={key:sorted(rows,key=lambda row:row['available_at']) for key,(_,rows) in indexed.items()}
    cursors={key:0 for key in indexed}
    output=[];daily={};volume_allocations={}
    for bar in sorted(bars.to_pylist(),key=lambda row:(row['available_at'],row['instrument_key'],row['bar_id'])):
        key=(bar['instrument_key'],bar['session_date']);levels={}
        times,all_trades=indexed.get(key,([],[]))
        if bar['bar_kind']=='VOLUME':
            target=bar['volume_target'];allocation_key=(*key,target)
            if allocation_key not in volume_allocations:
                allocation={};number=0;filled=0
                for trade in all_trades:
                    remaining=trade['volume']
                    while remaining>0:
                        amount=min(target-filled,remaining)
                        identity=f"{key[0]}:{key[1]}:V{target}:{number}"
                        allocation.setdefault(identity,[]).append(dict(trade,volume=amount))
                        remaining-=amount;filled+=amount
                        if filled==target:number+=1;filled=0
                volume_allocations[allocation_key]=allocation
            selected=volume_allocations[allocation_key].get(bar['bar_id'],[])
        else:
            begin=bisect_left(times,bar['bar_start']);end=bisect_left(times,bar['bar_end'])
            selected=all_trades[begin:end]
        for trade in selected:
            ts=trade['exchange_ts'] or trade['receipt_ts']
            if trade['available_at']>bar['available_at']:continue
            if trade['volume']==0:continue
            price=trade['price']
            if price%tick_size:raise ValueError('trade price is not tick-aligned')
            level=levels.setdefault(price,dict(bid=0,ask=0,unknown=0))
            name={'SELL':'bid','BUY':'ask','UNKNOWN':'unknown'}[trade['side']]
            level[name]+=trade['volume']
        session=daily.setdefault(key,{})
        history=available_rows.get(key,[]);cursor=cursors.get(key,0)
        while cursor<len(history) and history[cursor]['available_at']<=bar['available_at']:
            trade=history[cursor];price=trade['price']
            if trade['volume']:session[price]=session.get(price,0)+trade['volume']
            cursor+=1
        cursors[key]=cursor
        threshold=float(np.percentile(list(session.values()),percentile)) if session else 0
        buys,sells=diagonal(levels,tick_size=tick_size,ratio=ratio,min_volume=threshold)
        buy_stack=stacked(buys,tick_size=tick_size,count=stacked_levels)
        sell_stack=stacked(sells,tick_size=tick_size,count=stacked_levels)
        for price,level in sorted(levels.items()):
            output.append(dict(symbol=bar['symbol'],instrument_key=bar['instrument_key'],session_date=bar['session_date'],
                bar_id=bar['bar_id'],price=price,bid_volume=level['bid'],ask_volume=level['ask'],unknown_volume=level['unknown'],
                buy_imbalance=price in buys,sell_imbalance=price in sells,stacked_buy=price in buy_stack,stacked_sell=price in sell_stack,
                source=bar['source'],method='ESTIMATE',confidence=bar['confidence'],flags=bar['flags'],
                available_at=bar['available_at'],inputs=[dict(record_id=bar['bar_id'],available_at=bar['available_at'])]))
    return pa.Table.from_pylist(output,schema=FOOTPRINT_SCHEMA)
