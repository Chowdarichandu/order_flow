"""T09 session profile, value-area expansion, composites and IB known answers."""
from datetime import timedelta
from decimal import Decimal as D
import pyarrow as pa
from orderflow.layers.profile.core import profile_values,session_profile,composite_profile,naked_pocs,initial_balance
from orderflow.sim.history import candle_response
from orderflow.decode.candles import decode_candles
from test_trades_bars import START,ticks
from orderflow.trades.core import classify_ticks
from orderflow.bars.core import time_bars


def test_poc_tie_nearest_vwap_and_contiguous_value_area():
    levels={D('99'):10,D('100'):40,D('101'):40,D('102'):10}
    values=profile_values(levels,tick_size=D('1'),vwap=D('100.8'),value_area=.7)
    assert values['poc']==D('101') and values['val']==D('100') and values['vah']==D('101')


def test_three_tick_smoothed_local_nodes():
    levels={D(str(i)):v for i,v in enumerate([0,1,9,1,0,1,9,1,0])}
    values=profile_values(levels,tick_size=D('1'),vwap=D('4'),value_area=.7)
    assert D('2') in values['hvn'] and D('6') in values['hvn']
    assert D('4') in values['lvn']


def test_live_profile_and_truncation():
    data=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(100,30,99,101,[]),(102,40,99,101,[])]))
    cutoff=START+timedelta(seconds=25)
    full=session_profile(data,tick_size=D('1'),as_of=cutoff)
    short=session_profile(data.slice(0,3),tick_size=D('1'),as_of=cutoff)
    assert full.equals(short)
    row=full.to_pylist()[0]
    assert row['poc']==D('100') and row['vwap']==D('100.33333333')
    assert row['method']=='ESTIMATE' and row['available_at']<=cutoff


def test_candle_volume_spreads_evenly_and_is_approximate():
    candles=decode_candles(candle_response(START,1),symbol='TEST',instrument_key='NSE_EQ|TEST',receipt_ts=START+timedelta(minutes=1))
    row=session_profile(candles,tick_size=D('.1'),as_of=START+timedelta(minutes=1)).to_pylist()[0]
    assert len(row['levels'])==4 and all(abs(level['volume']-250)<1e-9 for level in row['levels'])
    assert row['method']=='APPROXIMATE'


def test_composite_deduplicates_developing_versions_and_naked_poc_retirement():
    trades=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[])]))
    profile=session_profile(trades,tick_size=D('1'),as_of=START+timedelta(minutes=1))
    combined=composite_profile(pa.concat_tables([profile,profile]),sessions=5,tick_size=D('1'),as_of=START+timedelta(minutes=2))
    assert sum(l['volume'] for l in combined.to_pylist()[0]['levels'])==10
    prior=[dict(price=D('100'),available_at=START-timedelta(days=1)),dict(price=D('105'),available_at=START-timedelta(days=1))]
    assert naked_pocs(prior,[D('100'),D('101')],as_of=START)==[D('105')]


def test_initial_balance_only_after_first_hour_closes():
    data=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(99,20,99,101,[])]))
    bars=time_bars(data,minutes=1,as_of=START+timedelta(hours=1))
    assert initial_balance(bars,as_of=START+timedelta(minutes=59))=={}
    ib=initial_balance(bars,as_of=START+timedelta(hours=1))
    assert ib['high']==D('101') and ib['low']==D('99') and ib['range']==D('2')
