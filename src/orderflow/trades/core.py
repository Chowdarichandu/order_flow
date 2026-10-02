"""Pure snapshot volume and aggressor estimation, BOOTSTRAP section 4.1."""
from datetime import datetime
from decimal import Decimal
from typing import Any
from itertools import chain
from bisect import bisect_left
import pyarrow as pa
from orderflow.schema import TICK_SCHEMA,TRADE_SCHEMA


def classify_ticks(ticks:pa.Table) -> pa.Table:
    """v_t=vtt_t-vtt_prev, reset/first=0; quote strictly before ltt, then tick rule.

    Quotes are valid only for noncrossed positive bid/ask, are strictly earlier
    than the trade, and were received before this trade's availability. UNKNOWN
    stays separate. Duplicates/stale records remain with zero volume and do not
    advance baselines. State is isolated per instrument and IST session.
    """
    if not ticks.schema.equals(TICK_SCHEMA):
        raise ValueError('canonical TickEvent schema required')
    states:dict[tuple,dict[str,Any]]={}
    output=[]
    for tick in chain.from_iterable(batch.to_pylist() for batch in ticks.to_batches(max_chunksize=10000)):
        key=(tick['instrument_key'],tick['session_date'])
        state=states.setdefault(key,dict(vtt=None,price=None,different=None,quote=None,quotes=[],quote_times=[]))
        flags=list(tick['flags'])
        skipped=bool({'OUT_OF_ORDER','DUPLICATE'} & set(flags))
        price=tick['ltp']
        if price is None:
            raise ValueError('TickEvent has no trade price; retain upstream and flag invalid input')
        volume=0
        side,confidence='UNKNOWN','UNKNOWN'
        quote_ts=None
        inputs=[dict(record_id=f"{tick['instrument_key']}:{tick['sequence']}",available_at=tick['receipt_ts'])]
        if not skipped:
            if tick['vtt'] is None:
                flags.append('MISSING_VOLUME')
            elif state['vtt'] is None:
                flags.append('FIRST_TICK')
            elif tick['vtt']<state['vtt'] or 'VOLUME_RESET' in flags:
                flags.append('VOLUME_RESET')
            else:
                volume=tick['vtt']-state['vtt']
            if state['price'] is not None and price!=state['price']:
                state['different']=state['price']
            trade_ts=tick['ltt'] or tick['exchange_ts']
            index=bisect_left(state['quote_times'],trade_ts)-1 if trade_ts is not None else -1
            quote=state['quotes'][index] if index>=0 else None
            if quote and quote['ts'] is not None and trade_ts is not None and quote['ts']<trade_ts and quote['available']<=tick['receipt_ts'] and quote['bid'] is not None:
                bid,ask=quote['bid'],quote['ask'];mid=(bid+ask)/2
                quote_ts=quote['ts']
                inputs.append(dict(record_id=quote['id'],available_at=quote['available']))
                if price>=ask:side,confidence='BUY','HIGH'
                elif price<=bid:side,confidence='SELL','HIGH'
                elif price>mid:side,confidence='BUY','MEDIUM'
                elif price<mid:side,confidence='SELL','MEDIUM'
            if side=='UNKNOWN' and state['different'] is not None:
                different=state['different']
                if price>different:side,confidence='BUY','LOW'
                elif price<different:side,confidence='SELL','LOW'
            state['vtt']=tick['vtt'] if tick['vtt'] is not None else state['vtt']
            state['price']=price
            bid=tick['bids'][0]['price'] if tick['bids'] else None
            ask=tick['asks'][0]['price'] if tick['asks'] else None
            valid=bid is not None and ask is not None and 0<bid<=ask
            state['quote']=dict(ts=tick['exchange_ts'],available=tick['receipt_ts'],
                               bid=bid if valid else None,ask=ask if valid else None,
                               id=f"{tick['instrument_key']}:{tick['sequence']}")
            if tick['exchange_ts'] is not None:
                state['quotes'].append(state['quote'])
                state['quote_times'].append(tick['exchange_ts'])
        bid_now=tick['bids'][0]['price'] if tick['bids'] else None
        ask_now=tick['asks'][0]['price'] if tick['asks'] else None
        mid_price=(bid_now+ask_now)/2 if bid_now is not None and ask_now is not None and 0<bid_now<=ask_now else None
        output.append(dict(symbol=tick['symbol'],instrument_key=tick['instrument_key'],
            session_date=tick['session_date'],sequence=tick['sequence'],exchange_ts=tick['exchange_ts'],
            receipt_ts=tick['receipt_ts'],price=price,mid_price=mid_price,volume=volume,side=side,quote_ts=quote_ts,
            source=tick['source'],method='ESTIMATE',confidence=confidence,
            flags=sorted(set(flags)),available_at=tick['receipt_ts'],inputs=inputs))
    return pa.Table.from_pylist(output,schema=TRADE_SCHEMA)
