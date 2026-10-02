"""T04 known answers for snapshot volume, strict quote rule and bar boundaries."""
from datetime import datetime,time,timedelta,timezone
from decimal import Decimal as D

import pyarrow as pa
import pytest
from orderflow.trades.core import classify_ticks
from orderflow.bars.core import time_bars,volume_bars
from orderflow.schema import TICK_SCHEMA,TRADE_SCHEMA,BAR_SCHEMA

START=datetime(2026,10,1,3,45,tzinfo=timezone.utc)


def ticks(spec):
    rows=[]
    for i,(price,vtt,bid,ask,flags) in enumerate(spec):
        ts=START+timedelta(seconds=i*10)
        rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),
            sequence=i,ltp=D(str(price)),ltq=1,ltt=ts,vtt=vtt,oi=None,
            bids=[dict(price=D(str(bid)),quantity=100,orders=None)] if bid else [],
            asks=[dict(price=D(str(ask)),quantity=100,orders=None)] if ask else [],
            tbq=100,tsq=100,exchange_ts=ts,receipt_ts=ts+timedelta(milliseconds=20),source='SIMULATOR',flags=flags))
    return pa.Table.from_pylist(rows,schema=TICK_SCHEMA)


def test_volume_quote_tick_rule_and_unknown_known_answer():
    data=ticks([(100,1000,99,101,[]),(101,1010,100,102,[]),
                (100,1030,99,101,[]),(100,1040,99,101,[]),(101,5,99,101,[])])
    out=classify_ticks(data).to_pylist()
    assert [r['volume'] for r in out] == [0,10,20,10,0]
    # The quote on the same snapshot cannot classify that snapshot's trade.
    assert [(r['side'],r['confidence']) for r in out] == [
        ('UNKNOWN','UNKNOWN'),('BUY','HIGH'),('SELL','HIGH'),('SELL','LOW'),('BUY','HIGH')]
    assert 'FIRST_TICK' in out[0]['flags'] and 'VOLUME_RESET' in out[-1]['flags']
    assert all(r['method']=='ESTIMATE' and r['available_at']==r['receipt_ts'] for r in out)


def test_same_timestamp_quote_is_excluded_and_medium_rule():
    data=ticks([(100,0,99,101,[]),(100.5,10,100,101,[]),(100.25,20,100,101,[])])
    rows=data.to_pylist()
    rows[1]['ltt']=rows[0]['exchange_ts']
    out=classify_ticks(pa.Table.from_pylist(rows,schema=TICK_SCHEMA)).to_pylist()
    assert out[1]['confidence']=='LOW'
    assert out[2]['side']=='SELL' and out[2]['confidence']=='MEDIUM'


def test_stale_duplicate_preserved_without_volume_double_count():
    data=ticks([(100,100,99,101,[]),(101,120,99,101,[]),(99,110,99,101,['OUT_OF_ORDER']),
                (101,120,99,101,['DUPLICATE']),(102,130,99,101,[])])
    out=classify_ticks(data).to_pylist()
    assert [r['volume'] for r in out]==[0,20,0,0,10]
    assert 'OUT_OF_ORDER' in out[2]['flags'] and 'DUPLICATE' in out[3]['flags']


def test_truncation_of_classifier_and_bars():
    data=ticks([(100+i*.1,10*i,99,101,[]) for i in range(20)])
    full=classify_ticks(data)
    short=classify_ticks(data.slice(0,10))
    assert full.slice(0,10).equals(short)
    cutoff=START+timedelta(minutes=1)
    assert time_bars(full,minutes=1,as_of=cutoff).equals(time_bars(short,minutes=1,as_of=cutoff))


@pytest.mark.parametrize('minutes',[1,5,15,60])
def test_time_bar_close_only_and_volume_conservation(minutes):
    data=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(99,30,99,101,[])]))
    cutoff=START+timedelta(minutes=minutes)
    before=time_bars(data,minutes=minutes,as_of=cutoff-timedelta(microseconds=1))
    assert before.num_rows==0
    bars=time_bars(data,minutes=minutes,as_of=cutoff)
    assert bars.schema.equals(BAR_SCHEMA)
    row=bars.to_pylist()[0]
    assert (row['open'],row['high'],row['low'],row['close'])==(D('100'),D('101'),D('99'),D('99'))
    assert row['volume']==30 and row['buy_volume']==10 and row['sell_volume']==20
    assert row['unknown_volume']==0 and row['delta']==-10 and row['cvd']==-10
    assert row['available_at']==cutoff


def test_unknown_separate_and_volume_bars_split_skipped_trades():
    data=classify_ticks(ticks([(100,0,None,None,[]),(100,25,None,None,[])]))
    bars=volume_bars(data,target=10,as_of=START+timedelta(minutes=1)).to_pylist()
    assert len(bars)==2
    assert all(r['volume']==10 and r['unknown_volume']==10 and r['delta']==0 for r in bars)
    assert all('SPLIT_SNAPSHOT_ESTIMATE' in r['flags'] for r in bars)


def test_time_boundary_tick_goes_into_next_bar():
    data=classify_ticks(ticks([(100+i,10*i,99,101,[]) for i in range(8)]))
    bars=time_bars(data,minutes=1,as_of=START+timedelta(minutes=2)).to_pylist()
    assert [r['close'] for r in bars]==[D('105'),D('107')]
    assert [r['volume'] for r in bars]==[50,20]


def test_history_candle_bars_preserve_observed_ohlcv_and_unknown_flow():
    from orderflow.sim.history import candle_response
    from orderflow.decode.candles import decode_candles
    from orderflow.bars.core import candle_bars
    candles=decode_candles(candle_response(START,5),symbol='TEST',instrument_key='NSE_EQ|TEST',
                            receipt_ts=START+timedelta(minutes=5))
    bars=candle_bars(candles,minutes=5,as_of=START+timedelta(minutes=5)).to_pylist()
    assert len(bars)==1 and bars[0]['volume']==5100
    assert bars[0]['high']==D('100.40') and bars[0]['low']==D('99.90')
    assert bars[0]['unknown_volume']==5100 and bars[0]['delta']==0
    assert bars[0]['method']=='APPROXIMATE'


def test_equal_trade_timestamp_uses_last_strictly_earlier_quote_history():
    data=ticks([(100,0,99,101,[]),(101,10,100,102,[]),(101,20,100.5,102,[])])
    rows=data.to_pylist();rows[2]['ltt']=rows[1]['ltt']
    out=classify_ticks(pa.Table.from_pylist(rows,schema=TICK_SCHEMA)).to_pylist()
    assert out[2]['quote_ts']==START and out[2]['confidence']=='HIGH'


def test_absent_trade_price_is_explicit_failure_not_silent_drop():
    rows=ticks([(100,0,99,101,[])]).to_pylist();rows[0]['ltp']=None
    with pytest.raises(ValueError,match='price'):
        classify_ticks(pa.Table.from_pylist(rows,schema=TICK_SCHEMA))


def session_ticks():
    """09:00 recorder start, regular open/close and 15:35 recorder stop."""
    offsets=[-900,-1,0,10,22499,22500,22800]
    rows=ticks([(100+i,100+10*i,99,101,[]) for i in range(len(offsets))]).to_pylist()
    for row,offset in zip(rows,offsets):
        row['exchange_ts']=row['ltt']=START+timedelta(seconds=offset)
        row['receipt_ts']=row['exchange_ts']+timedelta(milliseconds=20)
    return pa.Table.from_pylist(rows,schema=TICK_SCHEMA)


def test_regular_first_tick_and_outside_audit_phase_baselines():
    rows=classify_ticks(session_ticks()).to_pylist()
    assert len(rows)==7
    assert [row['volume'] for row in rows]==[0,10,0,10,10,0,10]
    assert ['OUTSIDE_SESSION' in row['flags'] for row in rows]==[True,True,False,False,False,True,True]
    assert all('FIRST_TICK' in rows[i]['flags'] for i in (0,2,5))
    # Regular phase volume resets without changing quote history or snapshot semantics.
    assert rows[2]['quote_ts']==START-timedelta(seconds=1)
    assert rows[2]['exchange_ts']==START and rows[2]['side']=='BUY'


def test_time_volume_bars_exclude_outside_window_and_start_regular_cvd():
    data=classify_ticks(session_ticks())
    cutoff=START+timedelta(hours=8)
    rows=time_bars(data,minutes=1,as_of=cutoff).to_pylist()
    assert [row['volume'] for row in rows]==[10,10]
    assert [row['cvd'] for row in rows]==[10,20]
    assert [row['open'] for row in rows]==[D('102'),D('104')]
    assert all('OUTSIDE_SESSION' not in row['flags'] for row in rows)
    rows=volume_bars(data,target=10,as_of=cutoff).to_pylist()
    assert [row['cvd'] for row in rows]==[10,20]
    assert [row['close'] for row in rows]==[D('103'),D('104')]


def test_regular_window_truncation_and_boundary_stale_tick():
    data=session_ticks()
    rows=data.to_pylist()
    rows[2]['flags']=['DUPLICATE']
    full=classify_ticks(pa.Table.from_pylist(rows,schema=TICK_SCHEMA))
    assert 'FIRST_TICK' in full.to_pylist()[3]['flags']
    assert full.to_pylist()[3]['volume']==0
    short=classify_ticks(pa.Table.from_pylist(rows[:4],schema=TICK_SCHEMA))
    assert full.slice(0,4).equals(short)
    cutoff=START+timedelta(minutes=1)
    assert time_bars(full,minutes=1,as_of=cutoff).equals(time_bars(short,minutes=1,as_of=cutoff))
    assert volume_bars(full,target=10,as_of=cutoff).equals(volume_bars(short,target=10,as_of=cutoff))


def test_explicit_optional_session_window_is_used_by_all_trade_apis():
    window=dict(session_open=time(9,0),session_close=time(9,16))
    data=classify_ticks(session_ticks(),**window)
    rows=data.to_pylist()
    assert [row['volume'] for row in rows]==[0,10,10,10,0,10,10]
    assert 'OUTSIDE_SESSION' not in rows[0]['flags']
    assert 'OUTSIDE_SESSION' in rows[4]['flags']
    cutoff=START+timedelta(hours=8)
    bars=time_bars(data,minutes=1,as_of=cutoff,**window).to_pylist()
    assert [row['cvd'] for row in bars]==[0,10,30]
    bars=volume_bars(data,target=10,as_of=cutoff,**window).to_pylist()
    assert [row['cvd'] for row in bars]==[10,20,30]


def test_last_60m_bucket_is_left_unclosed_after_regular_close():
    rows=session_ticks().to_pylist()
    for row,offset in zip(rows[:3],(21590,21600,22499)):
        row['exchange_ts']=row['ltt']=START+timedelta(seconds=offset)
        row['receipt_ts']=row['exchange_ts']+timedelta(milliseconds=20)
    data=classify_ticks(pa.Table.from_pylist(rows[:3],schema=TICK_SCHEMA))
    bars=time_bars(data,minutes=60,as_of=START+timedelta(hours=8)).to_pylist()
    assert len(bars)==1
    assert bars[0]['bar_end']==START+timedelta(hours=6)
    assert all(row['bar_start']!=START+timedelta(hours=6) for row in bars)


def session_candles(offsets):
    from orderflow.schema import CANDLE_SCHEMA
    rows=[]
    for offset in offsets:
        start=START+timedelta(minutes=offset)
        rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),
            bar_start=start,bar_end=start+timedelta(minutes=1),open=D('100'),high=D('101'),
            low=D('99'),close=D('100'),volume=10,oi=None,source='HISTORICAL_CANDLE_V3',
            method='OBSERVED',confidence='HIGH',flags=[],available_at=start+timedelta(minutes=1),inputs=[]))
    return pa.Table.from_pylist(rows,schema=CANDLE_SCHEMA)


def test_history_filters_outside_and_cross_boundary_coverage():
    from orderflow.bars.core import candle_bars
    from orderflow.schema import CANDLE_SCHEMA
    rows=session_candles([-1,0,374,375]).to_pylist()
    # Neither a pre-open candle overlapping regular trading nor a candle
    # beginning inside but ending outside has wholly regular coverage.
    rows[0]['bar_end']=START+timedelta(minutes=1)
    rows[3]['bar_start']=START+timedelta(minutes=374,seconds=30)
    data=pa.Table.from_pylist(rows,schema=CANDLE_SCHEMA)
    bars=candle_bars(data,minutes=1,as_of=START+timedelta(hours=8)).to_pylist()
    assert [row['bar_start'] for row in bars]==[START,START+timedelta(minutes=374)]
    assert [row['volume'] for row in bars]==[10,10]
    short=data.slice(0,2)
    cutoff=START+timedelta(minutes=1)
    assert candle_bars(data,minutes=1,as_of=cutoff).equals(candle_bars(short,minutes=1,as_of=cutoff))


def test_history_optional_window_and_last_60m_policy():
    from orderflow.bars.core import candle_bars
    data=session_candles([-15,-1,0,359,360,374,375])
    cutoff=START+timedelta(hours=8)
    bars=candle_bars(data,minutes=1,as_of=cutoff,
                     session_open=time(9,0),session_close=time(9,16)).to_pylist()
    assert [row['volume'] for row in bars]==[10,10,10]
    bars=candle_bars(data,minutes=60,as_of=cutoff).to_pylist()
    assert [row['bar_start'] for row in bars]==[START,START+timedelta(hours=5)]
    assert all(row['bar_end']<=START+timedelta(minutes=375) for row in bars)


def test_bars_filter_snapshot_boundaries_without_preclassified_flags():
    rows=classify_ticks(session_ticks()).to_pylist()
    for row in rows:row['flags']=[]
    data=pa.Table.from_pylist(rows,schema=TRADE_SCHEMA)
    cutoff=START+timedelta(hours=8)
    assert [row['volume'] for row in time_bars(data,minutes=1,as_of=cutoff).to_pylist()]==[10,10]
    assert [row['volume'] for row in volume_bars(data,target=10,as_of=cutoff).to_pylist()]==[10,10]


def test_session_membership_uses_snapshot_not_stale_last_trade_timestamp():
    rows=session_ticks().to_pylist()
    rows[2]['ltt']=rows[1]['ltt']
    rows[5]['ltt']=rows[4]['ltt']
    out=classify_ticks(pa.Table.from_pylist(rows,schema=TICK_SCHEMA)).to_pylist()
    assert 'OUTSIDE_SESSION' not in out[2]['flags'] and 'FIRST_TICK' in out[2]['flags']
    assert 'OUTSIDE_SESSION' in out[5]['flags']
    assert [row['exchange_ts'] for row in out]==[row['exchange_ts'] for row in rows]
